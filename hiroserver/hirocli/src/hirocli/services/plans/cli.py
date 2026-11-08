"""Running the plan tools (kinds.py): the one place that starts them (ported from HomeHiro's agents/cli.py).

- **Which copy.** The one the core installs and updates with npm in ``<workspace>/plans/tools``
  (updates.py); while that isn't installed, one on PATH (a developer's PC). Either way Node.js must be
  on PATH: npm's launchers run ``node``. A missing tool or Node is a clear ``NotInstalled``.
- **Their own folders.** Each tool keeps its login in ``<workspace>/plans/<tool>`` (``CLAUDE_CONFIG_DIR``,
  ``CODEX_HOME``), never the owner's own ~/.claude or ~/.codex: signing out here signs nobody out of the
  tools on their desktop.
- **A clean environment.** The tools get only what a program needs to run (PATH, the home and temp folders,
  the locale), never the core's own settings, tokens or provider keys.
- **Input closed** unless a prompt is written to it: with stdin open, ``codex exec`` waits for it to end.
- Plain ``subprocess`` in worker threads: the server's Windows event loop can't run subprocesses.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from hiro_commons.log import Logger

from .kinds import PlanKind, plain

log = Logger.get("PLANS")

WINDOWS = sys.platform == "win32"
PLANS_DIR = "plans"
# What a program needs to run; nothing of the core's own (provider keys, the keyring, tokens).
KEEP_ENV = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "HOME", "USERPROFILE", "APPDATA",
    "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "TZ",
)


class PlanToolError(RuntimeError):
    """A plan tool failed, timed out, or answered something the core can't read."""


class NotInstalled(PlanToolError):
    """The tool (or Node.js, which runs it) isn't installed where the core runs."""


@dataclass(frozen=True)
class RunResult:
    code: int
    out: str
    err: str
    ms: int


def plans_dir(workspace_path: Path) -> Path:
    return workspace_path / PLANS_DIR


def tool_home(workspace_path: Path, kind: PlanKind) -> Path:
    """The tool's own folder: its login, its settings, its model lists."""
    path = plans_dir(workspace_path) / kind.id
    path.mkdir(parents=True, exist_ok=True)
    return path


def tools_folder(workspace_path: Path) -> Path:
    """Where npm installs the tools (``--prefix``)."""
    return plans_dir(workspace_path) / "tools"


def work_folder(workspace_path: Path) -> Path:
    """Where the tools run: asks get a fresh folder inside, everything else the shared empty one."""
    path = plans_dir(workspace_path) / "work"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tools_bin(workspace_path: Path) -> Path:
    """The installed tools' commands (npm's global layout: the prefix itself on Windows, bin/ elsewhere)."""
    folder = tools_folder(workspace_path)
    return folder if WINDOWS else folder / "bin"


def command(workspace_path: Path, kind: PlanKind, args: tuple[str, ...]) -> list[str]:
    if shutil.which("node") is None:
        raise NotInstalled(f"{kind.name} needs Node.js, and `node` isn't on PATH where the core runs. Install Node.js 20+.")
    where = tools_bin(workspace_path)
    # The core's own copy first; on Windows shutil.which finds npm's claude.cmd / codex.cmd too.
    found = shutil.which(kind.program, path=str(where)) if where.exists() else None
    found = found or shutil.which(kind.program)
    if found:
        return [found, *args]
    raise NotInstalled(f"{kind.name} isn't installed yet: press Update (plan_update) to install it with npm.")


def base_environment() -> dict[str, str]:
    """What a program needs to run, and nothing of the core's own."""
    return {k: v for k, v in os.environ.items() if k.upper() in KEEP_ENV}


def environment(workspace_path: Path, kind: PlanKind) -> dict[str, str]:
    env = base_environment()
    env.update(
        {
            kind.home_var: str(tool_home(workspace_path, kind)),
            "NO_COLOR": "1",
            # One way of updating: the core's nightly npm run (updates.py), not the tools' own updaters.
            "DISABLE_AUTOUPDATER": "1",
            "PYTHONIOENCODING": "utf-8",  # for the fake tools in the tests
        }
    )
    return env


def run(
    workspace_path: Path,
    kind: PlanKind,
    args: tuple[str, ...],
    what: str,
    timeout: float,
    *,
    cwd: Path | None = None,
    stdin: str | None = None,
) -> RunResult:
    """Run the tool once and wait (blocks: call from a thread). ``stdin``: text for its input (a prompt: no
    quoting through npm's .cmd on Windows, and not in the process list), else its input is closed. At the
    time limit the tool and whatever it started are ended."""
    cmd = command(workspace_path, kind, args)
    started = time.perf_counter()
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd or work_folder(workspace_path),
            env=environment(workspace_path, kind),
            start_new_session=not WINDOWS,
        )
    except OSError as exc:
        raise PlanToolError(f"{kind.name} could not be started: {exc}") from exc
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        kill(proc)
        proc.communicate()
        raise PlanToolError(f"{kind.name} didn't finish {what} within {timeout:.0f} s.") from exc
    ms = int((time.perf_counter() - started) * 1000)
    if proc.returncode == 0:
        log.info(f"✅ Plan tool ran — {kind.name} · {what}", elapsed_ms=ms)
    else:  # not a failure by itself: its caller says why (e.g. Claude Code signed out ends with 1)
        log.info(f"⚠️ Plan tool ended with exit code {proc.returncode} — {kind.name} · {what}", elapsed_ms=ms)
    return RunResult(proc.returncode, plain(out or ""), plain(err or ""), ms)


def start(workspace_path: Path, kind: PlanKind, args: tuple[str, ...], output: IO[bytes]) -> subprocess.Popen:
    """Start the tool without waiting: what it prints goes to ``output``, its input stays open (a sign-in)."""
    cmd = command(workspace_path, kind, args)
    try:
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.STDOUT,
            cwd=work_folder(workspace_path),
            env=environment(workspace_path, kind),
            start_new_session=not WINDOWS,
        )
    except OSError as exc:
        raise PlanToolError(f"{kind.name} could not be started: {exc}") from exc


def kill(proc: subprocess.Popen) -> None:
    """End the tool and whatever it started (npm's codex.cmd runs node, which runs codex)."""
    if proc.poll() is not None:
        return
    if WINDOWS:
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("⚠️ Couldn't end a plan tool's process tree", error=str(exc), pid=proc.pid)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)  # its own session (start_new_session): the group is the tool's
        except ProcessLookupError:
            pass  # it ended meanwhile
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
