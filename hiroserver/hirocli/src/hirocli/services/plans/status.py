"""Who is signed in to each plan tool, and when the sign-in runs out (ported from HomeHiro's agents/health.py).

- The tool is asked who is signed in at most every READ_EVERY seconds (each read starts a program); a
  failed ask (``recheck``) has it read again next time.
- When the core signs a tool in (signin.py) it keeps the time in ``<workspace>/plans/<tool>/hiro_signin.json``;
  a tool whose sign-in ends by itself (Claude Code: 30 days, ``PlanKind.signin_days``) then shows when it
  ends, and needs attention from WARN_DAYS before.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hiro_commons.log import Logger

from . import cli
from .kinds import PlanKind, SignInStatus

log = Logger.get("PLANS")

READ_EVERY = 5 * 60  # seconds between two reads of a tool's sign-in status
STATUS_TIMEOUT = 20.0
WARN_DAYS = 3
_SIGNED_IN_FILE = "hiro_signin.json"

_read: dict[tuple[str, str], tuple[float, SignInStatus | str]] = {}
_lock = threading.Lock()


@dataclass(frozen=True)
class SignInView:
    status: SignInStatus | None  # None when it couldn't be read (``problem`` says why)
    problem: str | None
    signed_in_at: datetime | None  # when the core last signed it in
    ends_at: datetime | None  # when that sign-in ends by itself, when the tool's do
    attention: bool  # ends within WARN_DAYS, or signed out


def _key(workspace_path: Path, kind: PlanKind) -> tuple[str, str]:
    return (str(workspace_path), kind.id)


def recheck(workspace_path: Path, kind: PlanKind) -> None:
    """An ask failed, or the tool was signed in or out: read its status again next time (any thread)."""
    with _lock:
        _read.pop(_key(workspace_path, kind), None)


def read_status(workspace_path: Path, kind: PlanKind, *, fresh: bool = False) -> SignInStatus | str:
    """The tool's sign-in status, or why it can't be read; blocks (it may run the tool)."""
    key = _key(workspace_path, kind)
    with _lock:
        kept = _read.get(key)
    if kept and not fresh and time.monotonic() - kept[0] < READ_EVERY:
        return kept[1]
    result: SignInStatus | str
    try:
        r = cli.run(workspace_path, kind, kind.status_args, "sign-in status", STATUS_TIMEOUT)
    except cli.NotInstalled as exc:
        result = str(exc)
    except cli.PlanToolError as exc:
        result = f"Couldn't read whether {kind.name} is signed in: {exc}"
    else:
        try:  # only the tool's printout is parsed here, so a ValueError is an unreadable status
            result = kind.status(r.code, r.out, r.err)
        except ValueError as exc:
            result = f"Couldn't read whether {kind.name} is signed in: {exc}"
    with _lock:
        _read[key] = (time.monotonic(), result)
    return result


def signed_in_at(workspace_path: Path, kind: PlanKind) -> datetime | None:
    path = cli.tool_home(workspace_path, kind) / _SIGNED_IN_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("signed_in_at")
        return datetime.fromisoformat(raw) if raw else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError, AttributeError) as exc:
        log.warning(f"⚠️ Couldn't read when {kind.name} was signed in", error=str(exc))
        return None


def note_signed_in(workspace_path: Path, kind: PlanKind, at: datetime | None = None) -> None:
    path = cli.tool_home(workspace_path, kind) / _SIGNED_IN_FILE
    try:
        path.write_text(json.dumps({"signed_in_at": (at or datetime.now(UTC)).isoformat()}), encoding="utf-8")
    except OSError as exc:  # it is signed in all the same; only the days left can't be shown
        log.warning(f"⚠️ Couldn't keep when {kind.name} was signed in", error=str(exc))
    recheck(workspace_path, kind)


def note_signed_out(workspace_path: Path, kind: PlanKind) -> None:
    (cli.tool_home(workspace_path, kind) / _SIGNED_IN_FILE).unlink(missing_ok=True)
    recheck(workspace_path, kind)


def view(workspace_path: Path, kind: PlanKind, now: datetime | None = None) -> SignInView:
    now = now or datetime.now(UTC)
    read = read_status(workspace_path, kind)
    since = signed_in_at(workspace_path, kind)
    ends = since + timedelta(days=kind.signin_days) if since and kind.signin_days else None
    if isinstance(read, str):
        return SignInView(None, read, since, ends, True)
    attention = not read.signed_in or (ends is not None and ends - now <= timedelta(days=WARN_DAYS))
    return SignInView(read, None, since if read.signed_in else None, ends if read.signed_in else None, attention)
