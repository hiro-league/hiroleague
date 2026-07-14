"""Shared PID file-based process management utilities.

Design principles:
  - Only the child process writes its own PID (it knows its real PID).
  - The parent never writes the PID — it polls for the PID file to appear.
  - Only stop_process() removes the PID file — the child never deletes it.
  - stderr goes to a log file so crashes are diagnosable.
  - In source checkouts, spawn via ``uv run --directory`` so the correct
    workspace venv and editable packages are guaranteed.
  - In installed packages, fall back to ``sys.executable`` because the current
    venv already contains the installed Hiro packages.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from hiro_commons.constants.storage import RUN_DIR

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


_workspace_root_cache: Path | None = None


def find_workspace_root(start: Path | None = None) -> Path | None:
    """Walk up from *start* (defaults to this file) to find the uv workspace
    root — the directory containing ``pyproject.toml`` with ``[tool.uv.workspace]``.

    Returns None if no workspace root is found.
    The result is cached after the first successful lookup.
    """
    global _workspace_root_cache
    if _workspace_root_cache is not None:
        return _workspace_root_cache

    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        toml = candidate / "pyproject.toml"
        if toml.exists():
            try:
                data = tomllib.loads(toml.read_text(encoding="utf-8"))
                if "workspace" in data.get("tool", {}).get("uv", {}):
                    _workspace_root_cache = candidate
                    return candidate
            except Exception:
                pass
    return None


def uv_python_cmd() -> list[str]:
    """Return the Python command prefix for spawning Hiro child processes.

    In source checkouts, use ``uv run --directory`` to get the workspace venv
    regardless of how the parent process was launched (debugpy, entry-point
    scripts, Task Scheduler, etc.). In installed packages there is no uv
    workspace root, so use the current interpreter from the active install
    environment.
    """
    root = find_workspace_root()
    if root is not None:
        return ["uv", "run", "--directory", str(root), "python"]

    # PyPI / uv-tool / pipx installs do not include the source uv workspace.
    return [sys.executable]


def spawn_detached(
    cmd: list[str],
    env: dict[str, str] | None = None,
    stderr_log: Path | None = None,
) -> None:
    """Spawn a fully detached background process.

    The caller should NOT try to use the returned PID — the child writes its
    own PID via write_pid().  Use wait_for_pid() to wait for it.
    """
    effective_env = dict(os.environ) if env is None else dict(env)
    effective_env.setdefault("PYTHONUTF8", "1")
    effective_env.setdefault("PYTHONIOENCODING", "utf-8")
    stderr_target = open(stderr_log, "a") if stderr_log else subprocess.DEVNULL  # noqa: SIM115
    if sys.platform == "win32":
        subprocess.Popen(
            cmd,
            env=effective_env,
            creationflags=(
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            ),
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
        )
    else:
        subprocess.Popen(
            cmd,
            env=effective_env,
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
        )


def wait_for_pid(
    base_path: Path,
    pid_filename: str,
    *,
    timeout: float = 20.0,
    poll_interval: float = 0.15,
    stderr_log: Path | None = None,
) -> int:
    """Wait for a child process to write its PID file and confirm it is alive.

    Raises RuntimeError if the PID file doesn't appear within *timeout*
    seconds or the process is not running when checked.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = read_pid(base_path, pid_filename)
        if pid is not None and is_running(pid):
            return pid
        time.sleep(poll_interval)

    pid = read_pid(base_path, pid_filename)
    if pid is not None and is_running(pid):
        return pid
    stderr_tail = _stderr_tail(stderr_log)
    stderr_hint = f"\n\nRecent stderr:\n{stderr_tail}" if stderr_tail else ""
    raise RuntimeError(
        f"Child process did not start within {timeout}s "
        f"(pid_file={base_path / pid_filename}, last_pid={pid})"
        f"{stderr_hint}"
    )


def _stderr_tail(stderr_log: Path | None, *, max_lines: int = 40) -> str:
    if stderr_log is None or not stderr_log.exists():
        return ""
    try:
        lines = stderr_log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def pid_file(base_path: Path, pid_filename: str) -> Path:
    return base_path / pid_filename


def channel_pid_file(base_path: Path, channel_name: str) -> Path:
    # Channel pids live beside the server pid under <workspace>/run/, named
    # ``channel-<name>.pid`` to mirror the ``logs/channel-<name>.log`` convention.
    return base_path / RUN_DIR / f"channel-{channel_name}.pid"


def _proc_create_time(pid: int) -> float | None:
    """Process creation timestamp, used as a recycle-proof identity for a PID."""
    try:
        import psutil

        return psutil.Process(pid).create_time()
    except Exception:
        return None


def write_pid(base_path: Path, pid_filename: str, pid: int | None = None) -> None:
    # Line 1: pid. Line 2 (optional): the process create-time, so a later reader can tell our
    # process apart from a different process that the OS later assigned the same recycled PID.
    pid = pid or os.getpid()
    create_time = _proc_create_time(pid)
    payload = str(pid) if create_time is None else f"{pid}\n{create_time}"
    target = pid_file(base_path, pid_filename)
    # pid_filename may point into a subdir (e.g. run/server.pid); ensure it exists.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")


def read_pid(base_path: Path, pid_filename: str) -> int | None:
    target = pid_file(base_path, pid_filename)
    if not target.exists():
        return None
    try:
        # First line only — the file may also carry a create-time on line 2.
        return int(target.read_text(encoding="utf-8").splitlines()[0].strip())
    except (ValueError, OSError, IndexError):
        return None


def read_pid_record(base_path: Path, pid_filename: str) -> tuple[int | None, float | None]:
    """Return ``(pid, create_time)`` from the pid file. ``create_time`` is ``None`` for
    legacy single-line files (then liveness falls back to PID existence only)."""
    target = pid_file(base_path, pid_filename)
    if not target.exists():
        return None, None
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
        pid = int(lines[0].strip())
    except (ValueError, OSError, IndexError):
        return None, None
    create_time: float | None = None
    if len(lines) > 1 and lines[1].strip():
        try:
            create_time = float(lines[1].strip())
        except ValueError:
            create_time = None
    return pid, create_time


def remove_pid(base_path: Path, pid_filename: str) -> None:
    try:
        pid_file(base_path, pid_filename).unlink(missing_ok=True)
    except OSError:
        pass


def _pid_exists(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                # Suppress the console window that Windows would otherwise flash
                # briefly for each tasklist.exe invocation.
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def is_running(pid: int | None, create_time: float | None = None) -> bool:
    """True if ``pid`` is live. When ``create_time`` is given, also require the live process to
    have that creation timestamp — this rejects a recycled PID now owned by an unrelated process
    (e.g. a crashed server's PID later reused by svchost). Fails closed if it can't be verified."""
    if pid is None:
        return False
    if not _pid_exists(pid):
        return False
    if create_time is not None:
        live = _proc_create_time(pid)
        if live is None or abs(live - create_time) > 1.0:
            return False
    return True


def read_running_pid(base_path: Path, pid_filename: str) -> int | None:
    """Return the recorded pid only if that exact process is still alive (identity-verified).

    Defeats stale-pid-file false positives from PID recycling; clears the pid file when the
    recorded process is gone so status/start/stop stop reporting a dead server as running."""
    pid, create_time = read_pid_record(base_path, pid_filename)
    if pid is None:
        return None
    if is_running(pid, create_time):
        return pid
    remove_pid(base_path, pid_filename)
    return None


def kill_process(pid: int, *, include_tree: bool = False) -> bool:
    """Send termination signal. Returns True if the signal was sent.

    ``include_tree`` also kills child processes. Needed for launcher-wrapped
    processes — e.g. a channel plugin spawned via ``uv run`` where ``pid`` is the
    ``uv`` launcher and the real plugin is its child: signalling only the launcher
    would orphan the plugin (it keeps its network connections alive).
    """
    try:
        if sys.platform == "win32":
            args = ["taskkill", "/PID", str(pid), "/F"]
            if include_tree:
                args.append("/T")  # terminate the whole process tree
            subprocess.run(
                args,
                capture_output=True,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        elif include_tree:
            # Child was spawned with start_new_session, so it leads its own process
            # group; signal the group to catch launcher + real process together.
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def write_channel_pid(base_path: Path, channel_name: str, pid: int) -> None:
    target = channel_pid_file(base_path, channel_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(pid), encoding="utf-8")


def read_channel_pid(base_path: Path, channel_name: str) -> int | None:
    target = channel_pid_file(base_path, channel_name)
    if not target.exists():
        return None
    try:
        return int(target.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def remove_channel_pid(base_path: Path, channel_name: str) -> None:
    try:
        channel_pid_file(base_path, channel_name).unlink(missing_ok=True)
    except OSError:
        pass


def stop_process(base_path: Path, pid_filename: str) -> bool:
    pid, create_time = read_pid_record(base_path, pid_filename)
    if pid is None:
        return False
    if not is_running(pid, create_time):
        # Recorded process is gone (or the PID was recycled to something else) — clear the stale
        # file; never taskkill a PID we can't confirm is ours.
        remove_pid(base_path, pid_filename)
        return False
    killed = kill_process(pid)
    if killed:
        remove_pid(base_path, pid_filename)
    return killed
