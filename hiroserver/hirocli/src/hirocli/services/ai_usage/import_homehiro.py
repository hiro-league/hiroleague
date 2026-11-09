"""Importing HomeHiro's LLM usage history into the core's AI usage, once (Phase 7b).

Reads a copy of HomeHiro's ``homehiro.db`` (read-only): ``llmtotal`` (one row per UTC hour and key,
kept for good; two rows of one hour and key add up) and, for its pre-7a local providers
(``local:<server id>``), ``llmserver``. Each row becomes an ``ai_calls`` row of source ``home``:

- the use from what asked (``Ask a camera`` / ``Ask now`` → ``ask``, ``Wake word`` → ``wakeword``,
  ``Write text`` → ``write``, an app such as StudyHiro → ``study``, ``Try it`` → ``try_it``, anything
  else → ``other``); the label is the camera, else the question's or automation's name;
- the profile by its name: an AI profile with that label (7a imported HomeHiro's under their names),
  else kept as the row's profile name;
- the provider as the core names it (``gemini`` → ``google``, ``claude_cli`` → ``claude_code``,
  ``codex_cli`` → ``codex``, ``local:<id>`` → ``lm_studio`` / ``ollama``);
- kind ``question``; who pays, the result and the sums (requests, tokens, time, cost, estimate, unpriced) as they are.

Only HomeHiro's hours before the core's first Home row are taken: from then on the core counts Home's
asks itself. That makes the import safe to run again (a second run takes nothing). A dry run writes nothing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...domain.db import db_path, ensure_db
from ...domain.preferences import WorkspacePreferences
from .store import RESULTS, UsageCall, add_rows, hour_key

SOURCE = "home"
USES = {"Ask a camera": "ask", "Ask now": "ask", "Wake word": "wakeword", "Write text": "write", "Try it": "try_it"}
APP_USES = {"studyhiro": "study"}  # an app's requests are kept under its name
PROVIDERS = {"gemini": "google", "claude_cli": "claude_code", "codex_cli": "codex"}
SERVER_KINDS = {"lmstudio": "lm_studio", "ollama": "ollama"}


class UsageImportError(ValueError):
    """The file isn't a HomeHiro database with LLM usage."""


@dataclass
class UsageImport:
    rows: int = 0  # HomeHiro rows read
    imported: int = 0  # rows added to the core (a dry run: would add)
    requests: int = 0
    cost: float = 0.0
    first_hour: str | None = None
    last_hour: str | None = None
    cutoff: str | None = None  # the core's first Home hour (HomeHiro's hours from then on are left)
    notes: list[str] = field(default_factory=list)
    written: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def import_usage(workspace_path: Path, prefs: WorkspacePreferences, db_file: Path, *, dry_run: bool) -> UsageImport:
    totals, servers = _read(db_file)
    out = UsageImport(rows=len(totals))
    out.cutoff = _first_home_hour(workspace_path)
    by_label = {p.label: pid for pid, p in prefs.ai.profiles.items()}
    rows: list[tuple[str, UsageCall]] = []
    skipped = 0
    for t in totals:
        hour = _hour(t["hour"])
        if out.cutoff is not None and hour >= out.cutoff:
            skipped += 1
            continue
        call = _call(t, servers, by_label)
        rows.append((hour, call))
        out.requests += call.requests
        out.cost += call.cost
    if rows:
        out.first_hour, out.last_hour = min(h for h, _ in rows), max(h for h, _ in rows)
    if skipped:
        out.notes.append(f"{skipped} rows from {out.cutoff} on left out: the core counts Home's asks itself since then.")
    unknown = sorted({str(t["kind"]) for t in totals if _use(str(t["kind"])) == "other" and t["kind"] != "Other"})
    if unknown:
        out.notes.append(f"Counted under the use 'other': {', '.join(unknown)}.")
    # A dry run says how many rows it would add (imported) and writes nothing (written false).
    out.imported = len(rows)
    if not dry_run and rows:
        add_rows(workspace_path, rows)
        out.written = True
    return out


def _read(db_file: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not db_file.is_file():
        raise UsageImportError(f"No such file: {db_file}")
    try:
        # Read-only: the copy is never changed.
        conn = sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise UsageImportError(f"Can't open {db_file}: {exc}") from exc
    try:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "llmtotal" not in tables:
            raise UsageImportError(f"{db_file} has no LLM usage (llmtotal): is it HomeHiro's homehiro.db?")
        totals = [dict(r) for r in conn.execute("SELECT * FROM llmtotal ORDER BY hour")]
        servers: dict[str, str] = {}
        if "llmserver" in tables:
            for r in conn.execute("SELECT * FROM llmserver"):
                kind = SERVER_KINDS.get(str(dict(r).get("kind") or ""))
                if kind:
                    servers[str(r["id"])] = kind
        return totals, servers
    except sqlite3.Error as exc:
        raise UsageImportError(f"Can't read {db_file}: {exc}") from exc
    finally:
        conn.close()


def _first_home_hour(workspace_path: Path) -> str | None:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        row = conn.execute("SELECT MIN(hour) FROM ai_calls WHERE source = ?", (SOURCE,)).fetchone()
    return row[0] if row and row[0] else None


def _hour(value: Any) -> str:
    """HomeHiro's hour (SQLite text, UTC without a zone) as the core's hour key."""
    at = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return hour_key(at if at.tzinfo else at.replace(tzinfo=UTC))


def _use(kind: str) -> str:
    return USES.get(kind) or APP_USES.get(kind.strip().lower()) or "other"


def _provider(name: str, servers: dict[str, str]) -> str:
    if name.startswith("local:"):
        return servers.get(name.split(":", 1)[1], "lm_studio")
    return PROVIDERS.get(name, name)


def _call(t: dict[str, Any], servers: dict[str, str], by_label: dict[str, str]) -> UsageCall:
    kind = str(t.get("kind") or "Other")
    use = _use(kind)
    profile = str(t.get("profile") or "")
    billing = str(t.get("billing") or "api")
    result = str(t.get("result") or "ok")
    return UsageCall(
        kind="question",
        source=SOURCE,
        use=use,
        profile_id=by_label.get(profile, ""),
        profile_name=profile,
        provider=_provider(str(t.get("provider") or ""), servers),
        model=str(t.get("model") or ""),
        billing=billing if billing in ("api", "plan", "local") else "api",
        label=str(t.get("camera") or t.get("task") or ""),
        result=result if result in RESULTS else "ok",
        requests=int(t.get("requests") or 0),
        tokens_in=int(t.get("tokens_in") or 0),
        tokens_out=int(t.get("tokens_out") or 0),
        ms=int(t.get("ms") or 0),
        cost=float(t.get("cost") or 0.0),
        estimate=float(t.get("estimate") or 0.0),
        unpriced=int(t.get("unpriced") or 0),
    )
