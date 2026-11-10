"""An app's LAN name, kept by the core (docs/site-names-design.md).

An extension claims one name for its site (``reports.hiro.local`` or ``abc.local``) with the port it listens on; the
core keeps the claim here (workspace.db ``site_names``), publishes the name on the LAN and points Caddy at the port
(runtime/site_names.py). What lives here is the pure part: the name rules, the names Caddy's hand-written file
already serves (never touched, never given out), the Caddy file the core writes, and the claims table.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .db import db_path, ensure_db

DOMAIN = "hiro.local"  # hiro_channel_sdk.constants.SITES_DOMAIN
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_NAME = re.compile(rf"^{_LABEL}(?:\.hiro)?\.local$")
# Never given to an app, whatever Caddy's file says: the core's own address.
RESERVED = frozenset({DOMAIN})
# A site address line in a Caddyfile: "http://a.local, b.local {" (the addresses before the brace).
_SITE_LINE = re.compile(r"^\s*([^#{}\s][^#{}]*?)\s*\{\s*(?:#.*)?$")


class SiteNameError(ValueError):
    """A claim that can't be made as asked; ``code`` is the contract's error code, the message is for people."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SiteName:
    name: str
    extension_id: str
    port: int
    claimed_at: str = ""


def check_name(name: str) -> str:
    """The name as kept (lower case), or SiteNameError("invalid") with the rule in words."""
    clean = (name or "").strip().lower()
    if not _NAME.match(clean):
        raise SiteNameError(
            "invalid",
            f"“{name}” can't be an app's name: use a subdomain like reports.{DOMAIN}, or one word like abc.local "
            "(letters, digits and dashes).",
        )
    return clean


def check_port(port: object) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SiteNameError("invalid", "The app's port must be a number from 1 to 65535.")
    return port


def caddy_names(caddyfile: Path | None) -> set[str]:
    """The names a hand-written Caddyfile already serves (its site addresses, scheme and port dropped)."""
    if caddyfile is None or not caddyfile.is_file():
        return set()
    names: set[str] = set()
    for line in caddyfile.read_text(encoding="utf-8").splitlines():
        found = _SITE_LINE.match(line)
        if not found or found.group(1).strip().startswith(("import", "reverse_proxy", "handle", "@")):
            continue
        for address in found.group(1).split(","):
            host = re.sub(r"^[a-z]+://", "", address.strip().lower()).split("/")[0].split(":")[0]
            if host:
                names.add(host)
    return names


def render_caddy(claims: list[SiteName]) -> str:
    """The Caddy file the core owns: one block per claimed name, proxied to the app on this machine."""
    lines = [
        "# Written by HiroLeague (site names, docs/site-names-design.md): each app's LAN name, claimed from its address",
        "# setting. Don't edit: the core writes this file again on each change. Hand-written names go in the Caddyfile.",
    ]
    for c in sorted(claims, key=lambda c: c.name):
        lines += [
            "",
            f"http://{c.name} {{",
            f"\treverse_proxy 127.0.0.1:{c.port} {{",
            "\t\tflush_interval -1 # pass live updates (SSE) through at once",
            "\t}",
            "}",
        ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Claims (workspace.db)
# ---------------------------------------------------------------------------


def _connect(workspace_path: Path) -> sqlite3.Connection:
    ensure_db(workspace_path)
    conn = sqlite3.connect(str(db_path(workspace_path)))
    conn.row_factory = sqlite3.Row
    return conn


def list_claims(workspace_path: Path) -> list[SiteName]:
    with _connect(workspace_path) as conn:
        rows = conn.execute("SELECT name, extension_id, port, claimed_at FROM site_names ORDER BY name").fetchall()
    return [SiteName(r["name"], r["extension_id"], int(r["port"]), r["claimed_at"] or "") for r in rows]


def claim(workspace_path: Path, extension_id: str, name: str, port: int, hand_written: set[str]) -> tuple[SiteName, str | None]:
    """Give ``name`` to the extension (dropping its old one); the claim, and the old name it replaced (or None).

    Raises SiteNameError: ``invalid`` (the name or port), ``taken`` (another app's, Caddy's hand-written file's, or
    the core's own)."""
    name, port = check_name(name), check_port(port)
    if name in RESERVED or name in hand_written:
        raise SiteNameError("taken", f"{name} is already in use on this server. Pick another name.")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _connect(workspace_path) as conn:
        holder = conn.execute("SELECT extension_id FROM site_names WHERE name = ?", (name,)).fetchone()
        if holder is not None and holder["extension_id"] != extension_id:
            raise SiteNameError("taken", f"{name} is another app's name. Pick another name.")
        old = conn.execute(
            "SELECT name FROM site_names WHERE extension_id = ? AND name != ?", (extension_id, name)
        ).fetchone()
        conn.execute("DELETE FROM site_names WHERE extension_id = ?", (extension_id,))
        conn.execute(
            "INSERT INTO site_names (name, extension_id, port, claimed_at) VALUES (?, ?, ?, ?)",
            (name, extension_id, port, now),
        )
        conn.commit()
    return SiteName(name, extension_id, port, now), (old["name"] if old else None)


def release(workspace_path: Path, extension_id: str) -> str | None:
    """Drop the extension's name (it was removed); the name it held, or None."""
    with _connect(workspace_path) as conn:
        row = conn.execute("SELECT name FROM site_names WHERE extension_id = ?", (extension_id,)).fetchone()
        conn.execute("DELETE FROM site_names WHERE extension_id = ?", (extension_id,))
        conn.commit()
    return row["name"] if row else None
