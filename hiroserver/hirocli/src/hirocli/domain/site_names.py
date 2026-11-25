"""Every name the core serves on the LAN (docs/site-names-design.md): the pure rules and the two tables.

A name belongs to one of three:
- **an app:** its main name, claimed by the app itself (``sites.claim {name, port}``), and any extra names the owner
  adds beside it (``hiro sites add <name> --app <key>``); workspace.db ``site_names``, the ``extra`` column marking
  the owner's;
- **the core:** ``hiro.local`` for its admin and the gateway's name, from its config, never rows;
- **an other site:** a name or the machine's address the owner adds that is no app (``hiro sites add``): a target
  on this machine, optionally only some paths, or a name only announced; workspace.db ``other_sites``.

What lives here is the pure part: the name rules, what the core serves (each name once), and the two tables. The
front door's configuration is domain/front_door.py; announcing and loading it is runtime/site_names.py.
"""

from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .db import db_path, ensure_db

DOMAIN = "hiro.local"  # hiro_channel_sdk.constants.SITES_DOMAIN
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_NAME = re.compile(rf"^{_LABEL}(?:\.hiro)?\.local$")
# Never given to an app or a site: the core's own address.
RESERVED = frozenset({DOMAIN})
# The id the core's own names are written under (they are never rows of the claims table).
CORE_ID = "hiroleague"
# The id an other site is served under: it belongs to no app.
OTHER_ID = "site"
# A path a site may be limited to: /tv, /_app/*, /api/tv/screen/* (Caddy's path matcher, one trailing * allowed).
_PATH = re.compile(r"^/[A-Za-z0-9._~\-/]*\*?$")
_HOST = re.compile(rf"^(?:{_LABEL}\.)*{_LABEL}$")
LOOPBACK = "127.0.0.1"


class SiteNameError(ValueError):
    """A claim that can't be made as asked; ``code`` is the contract's error code, the message is for people."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SiteName:
    """A row of ``site_names``: an app's name. ``extra`` marks a name the owner added beside the app's main one."""

    name: str
    extension_id: str
    port: int
    claimed_at: str = ""
    extra: bool = False


@dataclass(frozen=True)
class OtherSite:
    """A row of ``other_sites``: a site that is no app. ``target`` empty = the name is only announced."""

    name: str
    target: str = ""
    paths: tuple[str, ...] = ()
    added_at: str = ""

    @property
    def announce_only(self) -> bool:
        return not self.target


@dataclass(frozen=True)
class Site:
    """One name the core serves: where the front door sends it, and whether the name is announced on the LAN."""

    name: str
    owner: str  # an app's extension id, CORE_ID, or OTHER_ID
    upstream: str = ""  # host:port on this machine; empty = announced only, never proxied
    paths: tuple[str, ...] = ()  # only these are passed on (the rest answers 404); empty = every path
    announce: bool = True  # False for the machine's address: an address isn't a name to announce


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


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


def is_address(name: str) -> bool:
    """True for an IPv4 address (the machine's own, which a device without .local names reaches it by)."""
    try:
        return isinstance(ipaddress.ip_address(name), ipaddress.IPv4Address)
    except ValueError:
        return False


def check_site_name(name: str) -> str:
    """An other site's name: a .local name as an app's, or this machine's IPv4 address."""
    clean = (name or "").strip().lower()
    if is_address(clean):
        return clean
    try:
        return check_name(clean)
    except SiteNameError as exc:
        raise SiteNameError(
            "invalid", f"“{name}” can't be a site's name: use a .local name like adguard.local, or this machine's "
            "address like 192.168.1.10."
        ) from exc


def check_target(target: str) -> str:
    """Where a site points: ``8100``, ``127.0.0.1:3001`` or ``host:port``; kept as ``host:port``."""
    text = (target or "").strip().lower()
    host, sep, port_text = text.rpartition(":")
    if not sep:
        host, port_text = LOOPBACK, text
    try:
        port = int(port_text)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535 or not (is_address(host) or _HOST.match(host)):
        raise SiteNameError("invalid", f"“{target}” can't be a site's target: give a port (3001) or host:port "
                                       "(127.0.0.1:3001).")
    return f"{host}:{port}"


def check_paths(paths: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    out: list[str] = []
    for p in paths:
        clean = (p or "").strip()
        if not _PATH.match(clean) or "//" in clean:
            raise SiteNameError("invalid", f"“{p}” can't be a site's path: start it with / (like /tv or /_app/*).")
        if clean not in out:
            out.append(clean)
    return tuple(out)


def gateway_name(gateway_url: str) -> str | None:
    """The LAN name devices are given for the gateway (``ws://gate.hiro.local`` → ``gate.hiro.local``), or None when
    the address isn't a name the core can serve (``localhost``, an IP address, a name outside ``.local``)."""
    host = re.sub(r"^[a-z]+://", "", (gateway_url or "").strip().lower()).split("/")[0].split(":")[0]
    try:
        name = check_name(host)
    except SiteNameError:
        return None
    return None if name == DOMAIN else name


def core_names(*, admin_port: int, gateway_url: str, gateway_port: int, gateway_builtin: bool) -> list[SiteName]:
    """The core's own names, claimed as an app claims its own: ``hiro.local`` for its admin, and the gateway's name
    when the core runs the gateway itself (a gateway run elsewhere is served there)."""
    names = [SiteName(DOMAIN, CORE_ID, admin_port)]
    gate = gateway_name(gateway_url)
    if gate and gateway_builtin:
        names.append(SiteName(gate, CORE_ID, gateway_port))
    return names


def taken_by_core(config: Any) -> set[str]:
    """What no app or site may take: the core's own names, from its config (its gateway's name even when the gateway
    runs elsewhere: devices are given it)."""
    own = core_names(admin_port=config.admin_port, gateway_url=config.gateway_url, gateway_port=config.gateway_port,
                     gateway_builtin=config.gateway_builtin)
    gate = gateway_name(config.gateway_url)
    return {c.name for c in own} | ({gate} if gate else set())


@dataclass(frozen=True)
class Served:
    """What the core serves: every name once."""

    sites: list[Site]
    # The core's names an app's claim already holds (kept from before the core claimed them): the app keeps it.
    clashes: frozenset[str]


def served(claims: list[SiteName], core: list[SiteName], others: list[OtherSite]) -> Served:
    """The names to announce and to load into the front door: the apps' names, the core's own that no app holds, then
    the other sites. A name is never there twice (each table's key is the name, and adding refuses a taken one), so
    Caddy always takes the configuration."""
    sites = [Site(c.name, c.extension_id, f"{LOOPBACK}:{c.port}") for c in claims]
    seen = {s.name for s in sites}
    clashes = frozenset(c.name for c in core if c.name in seen)
    for c in core:
        if c.name not in seen:
            sites.append(Site(c.name, CORE_ID, f"{LOOPBACK}:{c.port}"))
            seen.add(c.name)
    for o in others:
        if o.name not in seen:
            sites.append(Site(o.name, OTHER_ID, o.target, o.paths, announce=not is_address(o.name)))
            seen.add(o.name)
    return Served(sites, clashes)


# ---------------------------------------------------------------------------
# The tables (workspace.db)
# ---------------------------------------------------------------------------


def _connect(workspace_path: Path) -> sqlite3.Connection:
    ensure_db(workspace_path)
    conn = sqlite3.connect(str(db_path(workspace_path)))
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_claims(workspace_path: Path) -> list[SiteName]:
    """Every app's names, the main ones and the extra ones."""
    with _connect(workspace_path) as conn:
        rows = conn.execute(
            "SELECT name, extension_id, port, claimed_at, extra FROM site_names ORDER BY name"
        ).fetchall()
    return [SiteName(r["name"], r["extension_id"], int(r["port"]), r["claimed_at"] or "", bool(r["extra"]))
            for r in rows]


def list_other_sites(workspace_path: Path) -> list[OtherSite]:
    with _connect(workspace_path) as conn:
        rows = conn.execute("SELECT name, target, paths, added_at FROM other_sites ORDER BY name").fetchall()
    return [OtherSite(r["name"], r["target"] or "", tuple(json.loads(r["paths"] or "[]")), r["added_at"] or "")
            for r in rows]


def _holder(conn: sqlite3.Connection, name: str) -> str | None:
    """Who holds ``name`` in the tables: an app's extension id, OTHER_ID, or None."""
    row = conn.execute("SELECT extension_id FROM site_names WHERE name = ?", (name,)).fetchone()
    if row is not None:
        return str(row["extension_id"])
    if conn.execute("SELECT 1 FROM other_sites WHERE name = ?", (name,)).fetchone() is not None:
        return OTHER_ID
    return None


def claim(workspace_path: Path, extension_id: str, name: str, port: int, taken: set[str]) -> tuple[SiteName, str | None]:
    """Give ``name`` to the extension as its main name (dropping its old main one; its extra names follow the new
    port); the claim, and the old name it replaced (or None).

    Raises SiteNameError: ``invalid`` (the name or port), ``taken`` (another app's, an other site's, one of this
    app's extra names, or the core's own: ``taken`` holds the core's names)."""
    name, port = check_name(name), check_port(port)
    if name in RESERVED or name in taken:
        raise SiteNameError("taken", f"{name} is already in use on this server. Pick another name.")
    now = _now()
    with _connect(workspace_path) as conn:
        holder = conn.execute("SELECT extension_id, extra FROM site_names WHERE name = ?", (name,)).fetchone()
        if holder is not None and (holder["extension_id"] != extension_id or holder["extra"]):
            raise SiteNameError("taken", f"{name} is another app's name. Pick another name.")
        if holder is None and _holder(conn, name) == OTHER_ID:
            raise SiteNameError("taken", f"{name} is already in use on this server. Pick another name.")
        old = conn.execute(
            "SELECT name FROM site_names WHERE extension_id = ? AND extra = 0 AND name != ?", (extension_id, name)
        ).fetchone()
        conn.execute("DELETE FROM site_names WHERE extension_id = ? AND extra = 0", (extension_id,))
        conn.execute(
            "INSERT INTO site_names (name, extension_id, port, claimed_at, extra) VALUES (?, ?, ?, ?, 0)",
            (name, extension_id, port, now),
        )
        conn.execute("UPDATE site_names SET port = ? WHERE extension_id = ? AND extra = 1", (port, extension_id))
        conn.commit()
    return SiteName(name, extension_id, port, now), (old["name"] if old else None)


def add_extra(workspace_path: Path, extension_id: str, name: str, taken: set[str]) -> SiteName:
    """An extra name beside the app's main one, sent to the same port. The app must have claimed its main name."""
    name = check_name(name)
    if name in RESERVED or name in taken:
        raise SiteNameError("taken", f"{name} is already in use on this server.")
    with _connect(workspace_path) as conn:
        main = conn.execute(
            "SELECT port FROM site_names WHERE extension_id = ? AND extra = 0", (extension_id,)
        ).fetchone()
        if main is None:
            raise SiteNameError("invalid", "This app has no name yet: it claims its own when it connects, then an "
                                           "extra name can go beside it.")
        if _holder(conn, name) is not None:
            raise SiteNameError("taken", f"{name} is already in use on this server.")
        now = _now()
        conn.execute(
            "INSERT INTO site_names (name, extension_id, port, claimed_at, extra) VALUES (?, ?, ?, ?, 1)",
            (name, extension_id, int(main["port"]), now),
        )
        conn.commit()
    return SiteName(name, extension_id, int(main["port"]), now, extra=True)


def add_other_site(workspace_path: Path, name: str, target: str, paths: list[str], taken: set[str]) -> OtherSite:
    """A site that is no app: ``target`` empty = the name is only announced (an address can't be: nothing to say)."""
    name = check_site_name(name)
    clean_target = check_target(target) if (target or "").strip() else ""
    clean_paths = check_paths(paths)
    if not clean_target and (clean_paths or is_address(name)):
        raise SiteNameError("invalid", "A site with paths, or on the machine's address, needs a target to send "
                                       "them to.")
    if name in RESERVED or name in taken:
        raise SiteNameError("taken", f"{name} is already in use on this server.")
    now = _now()
    with _connect(workspace_path) as conn:
        if _holder(conn, name) is not None:
            raise SiteNameError("taken", f"{name} is already in use on this server.")
        conn.execute(
            "INSERT INTO other_sites (name, target, paths, added_at) VALUES (?, ?, ?, ?)",
            (name, clean_target, json.dumps(list(clean_paths)), now),
        )
        conn.commit()
    return OtherSite(name, clean_target, clean_paths, now)


def remove_site(workspace_path: Path, name: str) -> str:
    """Drop an extra name or an other site; what it was (``extra`` or ``site``). An app's main name isn't the
    owner's to drop: it goes with the app (``hiro extension remove``) or the app's next claim."""
    clean = (name or "").strip().lower()
    with _connect(workspace_path) as conn:
        row = conn.execute("SELECT extra FROM site_names WHERE name = ?", (clean,)).fetchone()
        if row is not None:
            if not row["extra"]:
                raise SiteNameError("invalid", f"{clean} is an app's own name: it goes when the app is removed, or "
                                               "when the app claims another.")
            conn.execute("DELETE FROM site_names WHERE name = ?", (clean,))
            conn.commit()
            return "extra"
        if conn.execute("DELETE FROM other_sites WHERE name = ?", (clean,)).rowcount:
            conn.commit()
            return "site"
    raise SiteNameError("not_found", f"No site is named {clean}.")


def release(workspace_path: Path, extension_id: str) -> str | None:
    """Drop every name of the extension (it was removed); its main name, or None."""
    with _connect(workspace_path) as conn:
        row = conn.execute(
            "SELECT name FROM site_names WHERE extension_id = ? AND extra = 0", (extension_id,)
        ).fetchone()
        conn.execute("DELETE FROM site_names WHERE extension_id = ?", (extension_id,))
        conn.commit()
    return row["name"] if row else None
