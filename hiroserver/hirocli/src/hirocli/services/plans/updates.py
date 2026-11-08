"""Installing and updating the plan tools with npm into ``<workspace>/plans/tools`` (ported from HomeHiro's
agents/updates.py).

The core installs Claude Code and Codex there and updates both to their latest versions once a night after
UPDATE_HOUR (the server's local time), run by the AI background job (services/ai_background.py), or when the
admin presses Update (``plan_update``). The tools' own updaters stay off (cli.py): one way of updating, logged
and shown on the admin. npm (and Node.js, which runs the tools) must be on PATH; without it the run fails with
a clear message and nothing else changes.

The nightly run only happens in a workspace that uses plan tools: one whose tools folder exists (installed
once by Update) or with an AI profile on a plan tool, so a fresh workspace never downloads ~500 MB unasked.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from . import cli
from .kinds import PLAN_KINDS

log = Logger.get("PLANS")

UPDATE_HOUR = 4  # local time: after this, once a day
TIMEOUT = 15 * 60  # seconds for one npm run (about 500 MB the first time)
_STATE_FILE = "updates.json"


@dataclass
class UpdateState:
    folder: str
    running: bool = False
    last_run: str | None = None  # ISO, UTC
    ok: bool | None = None  # how the last run went
    message: str | None = None  # what it changed, or what went wrong
    versions: dict[str, str] = field(default_factory=dict)  # tool id → installed version
    next_run: str | None = None  # ISO, local

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def due(last_run: datetime | None, now: datetime, hour: int = UPDATE_HOUR) -> bool:
    """Whether the nightly update should run now: once a day, after ``hour`` of ``now``'s day (its zone)."""
    if last_run is None:
        return True
    start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    return last_run < start


def next_run(now: datetime, hour: int = UPDATE_HOUR) -> datetime:
    start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return start if now < start else start + timedelta(days=1)


def changes(before: dict[str, str], after: dict[str, str]) -> str:
    """ "Claude Code 2.1.284 → 2.1.290; Codex 0.159.0 (no change)" """
    parts = []
    for kind in PLAN_KINDS.values():
        old, new = before.get(kind.id), after.get(kind.id)
        if not new:
            parts.append(f"{kind.name} missing")
        elif not old:
            parts.append(f"{kind.name} {new} installed")
        elif old != new:
            parts.append(f"{kind.name} {old} → {new}")
        else:
            parts.append(f"{kind.name} {new} (no change)")
    return "; ".join(parts)


def installed_versions(folder: Path) -> dict[str, str]:
    """The versions npm installed, read from the packages themselves (npm's global layout)."""
    modules = folder / "node_modules" if cli.WINDOWS else folder / "lib" / "node_modules"
    found: dict[str, str] = {}
    for kind in PLAN_KINDS.values():
        try:
            found[kind.id] = str(json.loads((modules / kind.package / "package.json").read_text("utf-8"))["version"])
        except FileNotFoundError:
            continue  # not installed (yet)
        except (OSError, ValueError, KeyError) as exc:
            log.warning(f"⚠️ Couldn't read {kind.name}'s installed version", error=str(exc))
    return found


class Updater:
    """npm runs per workspace, one at a time each. Thread-safe."""

    def __init__(self) -> None:
        self._busy: set[str] = set()
        self._lock = threading.Lock()

    def state(self, workspace_path: Path) -> UpdateState:
        folder = cli.tools_folder(workspace_path)
        saved = _load(folder)
        with self._lock:
            running = str(workspace_path) in self._busy
        return UpdateState(
            folder=str(folder),
            running=running,
            last_run=saved.get("last_run"),
            ok=saved.get("ok"),
            message=saved.get("message"),
            versions=installed_versions(folder),
            next_run=next_run(datetime.now().astimezone()).isoformat(),
        )

    def update(self, workspace_path: Path, *, background: bool) -> UpdateState:
        """Install / update now, unless a run is going. ``background``: in a thread, return at once."""
        key = str(workspace_path)
        with self._lock:
            if key in self._busy:
                return self.state(workspace_path)
            self._busy.add(key)
        if background:
            threading.Thread(target=self._run, args=(workspace_path,), name="plan-tools-update", daemon=True).start()
            return self.state(workspace_path)
        self._run(workspace_path)
        return self.state(workspace_path)

    def nightly_due(self, workspace_path: Path, *, uses_plans: bool) -> bool:
        """Whether the nightly job should update now (see the module notes)."""
        folder = cli.tools_folder(workspace_path)
        if not (folder.exists() or uses_plans):
            return False
        if len(installed_versions(folder)) < len(PLAN_KINDS):
            return True
        last = _load(folder).get("last_run")
        last_at = datetime.fromisoformat(last).astimezone() if last else None
        return due(last_at, datetime.now().astimezone())

    def _run(self, workspace_path: Path) -> None:
        try:
            self._install(workspace_path)
        except Exception as exc:  # a thread of its own: log, never lose the busy flag
            log.error("❌ Plan tools update crashed", error=str(exc), exc_info=True)
        finally:
            with self._lock:
                self._busy.discard(str(workspace_path))

    def _install(self, workspace_path: Path) -> None:
        folder = cli.tools_folder(workspace_path)
        folder.mkdir(parents=True, exist_ok=True)
        before = installed_versions(folder)
        ok, message = True, ""
        cache = folder / ".npm-cache"  # its own, emptied after each run: npm's usual one would grow every night
        try:
            npm = shutil.which("npm")
            if not npm:
                raise cli.NotInstalled("npm isn't on PATH where the core runs: install Node.js 20+ (it brings npm).")
            if shutil.which("node") is None:
                raise cli.NotInstalled("Node.js isn't on PATH where the core runs: install Node.js 20+.")
            cmd = [
                npm, "install", "--global", "--prefix", str(folder), "--no-audit", "--no-fund", "--loglevel=error",
                *(f"{k.package}@latest" for k in PLAN_KINDS.values()),
            ]
            env = {**cli.base_environment(), "npm_config_cache": str(cache), "npm_config_update_notifier": "false"}
            log.info("⬇️ Plan tools update started", folder=str(folder))
            p = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=TIMEOUT, env=env,
            )
            if p.returncode != 0:
                ok, message = False, f"npm failed (exit code {p.returncode}): {(p.stderr or p.stdout).strip()[-400:]}"
        except subprocess.TimeoutExpired:
            ok, message = False, f"npm didn't finish within {TIMEOUT // 60} min."
        except (cli.NotInstalled, OSError) as exc:
            ok, message = False, str(exc)
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        after = installed_versions(folder)
        if ok:
            message = changes(before, after)
            log.info(f"✅ Plan tools updated — {message}")
        else:
            log.warning("⚠️ Plan tools update failed", error=message)
        _save(folder, {"last_run": datetime.now(UTC).isoformat(), "ok": ok, "message": message})


def _load(folder: Path) -> dict[str, Any]:
    try:
        return dict(json.loads((folder / _STATE_FILE).read_text("utf-8")))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError) as exc:
        log.warning("⚠️ Couldn't read the last plan tools update", error=str(exc))
        return {}


def _save(folder: Path, data: dict[str, Any]) -> None:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / _STATE_FILE).write_text(json.dumps(data), encoding="utf-8")
    except OSError as exc:
        log.warning("⚠️ Couldn't keep the plan tools update's outcome", error=str(exc))


updater = Updater()
