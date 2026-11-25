"""Mac service support for Hiro executables, through launchd: install, remove, start, stop and read its state.

On a Mac a Hiro server runs as a LaunchDaemon (``/Library/LaunchDaemons/<label>.plist``): launchd starts it at boot
with nobody signed in and runs it as the account named in ``UserName``. ``KeepAlive`` is ``{SuccessfulExit: false}``,
the same as systemd's ``Restart=on-failure``: a crash or any exit but 0 (75 included) starts it again after
``ThrottleInterval``, and a clean exit leaves it stopped.

A LaunchDaemon's plist must be owned by root and is readable by every account, so secrets never go in it: the
program reads its secrets file itself (:mod:`hiro_commons.env_file`), named by an environment variable.

Installing and removing write under ``/Library`` and need root; the caller checks first and tells the person the exact
``sudo`` command. Rendering and parsing are pure so they can be unit-tested anywhere; everything that touches the
system is Mac-only.
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .log import Logger
# One error type for every system's service, so a caller catches the same one on Linux, Windows and Mac.
from .systemd_service import ServiceError

log = Logger.get("SERVICE")

LAUNCH_DAEMONS_DIR = Path("/Library/LaunchDaemons")
LAUNCHCTL = "/bin/launchctl"
DOMAIN = "system"
_LABEL_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COMMAND_TIMEOUT_S = 120
# launchctl print's exit status for a service it doesn't know.
_NOT_FOUND = 113


@dataclass(frozen=True)
class LaunchdSpec:
    """Everything a LaunchDaemon's plist needs. ``program_args[0]`` must be an absolute path."""

    label: str
    user: str
    program_args: list[str]
    working_directory: Path
    log_path: Path
    environment: dict[str, str] = field(default_factory=dict)
    # Seconds launchd waits before starting it again (the systemd unit's RestartSec).
    throttle_interval_s: int = 5
    # Seconds a stop waits after SIGTERM before SIGKILL (the systemd unit's TimeoutStopSec).
    exit_timeout_s: int = 60


@dataclass
class ServiceState:
    """What launchd reports about a service (``installed`` False when it doesn't know it)."""

    label: str
    installed: bool
    state: str = "unknown"  # running, not running, spawn scheduled...
    pid: int | None = None
    last_exit_code: int | None = None
    runs: int | None = None
    plist_path: Path | None = None


# ---------------------------------------------------------------------------
# Names and paths
# ---------------------------------------------------------------------------


def validate_label(label: str) -> str:
    if not label or not _LABEL_RE.match(label):
        raise ServiceError(f"'{label}' is not a valid launchd label: use letters, digits, '-', '_' or '.'.")
    return label


def plist_path(label: str) -> Path:
    return LAUNCH_DAEMONS_DIR / f"{validate_label(label)}.plist"


def service_target(label: str) -> str:
    return f"{DOMAIN}/{validate_label(label)}"


# ---------------------------------------------------------------------------
# Rendering and parsing (pure)
# ---------------------------------------------------------------------------


def render_plist(spec: LaunchdSpec) -> bytes:
    """Return the plist bytes for ``spec``."""
    validate_label(spec.label)
    if not spec.program_args or not PurePosixPath(spec.program_args[0]).is_absolute():
        raise ServiceError("The service's program must be an absolute path.")
    if not spec.user or spec.user == "root":
        raise ServiceError("A Hiro service must run as a regular user, not root.")
    for key in spec.environment:
        if not _ENV_NAME_RE.match(key):
            raise ServiceError(f"'{key}' is not a valid environment variable name.")
    doc = {
        "Label": spec.label,
        "ProgramArguments": list(spec.program_args),
        "UserName": spec.user,
        "WorkingDirectory": spec.working_directory.as_posix(),
        "EnvironmentVariables": dict(spec.environment),
        # At boot, and again after a crash or any exit but 0; a clean exit stays stopped (Restart=on-failure).
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": spec.throttle_interval_s,
        "ExitTimeOut": spec.exit_timeout_s,
        # What the program writes before its own log file is open (a failed start) lands here.
        "StandardOutPath": spec.log_path.as_posix(),
        "StandardErrorPath": spec.log_path.as_posix(),
        "ProcessType": "Standard",
    }
    return plistlib.dumps(doc, fmt=plistlib.FMT_XML, sort_keys=False)


_PRINT_FIELD_RE = re.compile(r"^\s*([a-z][a-z ]*[a-z])\s*=\s*(.*?)\s*$")


def parse_print_output(label: str, text: str) -> ServiceState:
    """Turn ``launchctl print system/<label>`` output into a :class:`ServiceState`.

    Only the service's own top-level fields are read (one tab deep); nested blocks (its environment, endpoints) hold
    the same names for other things.
    """
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("\t") or line.startswith("\t\t"):
            continue
        match = _PRINT_FIELD_RE.match(line)
        if match and match.group(1) not in fields:
            fields[match.group(1)] = match.group(2)

    def number(key: str) -> int | None:
        value = fields.get(key, "")
        return int(value) if value.lstrip("-").isdigit() else None

    pid = number("pid")
    return ServiceState(
        label=label,
        installed=True,
        state=fields.get("state", "unknown"),
        pid=pid if pid and pid > 0 else None,
        last_exit_code=number("last exit code"),
        runs=number("runs"),
        plist_path=Path(fields["path"]) if fields.get("path") else None,
    )


# ---------------------------------------------------------------------------
# System access (Mac only)
# ---------------------------------------------------------------------------


def require_mac() -> None:
    if sys.platform != "darwin":
        raise ServiceError("This is the Mac service (launchd); this system is not a Mac.")


def _run(cmd: list[str], *, timeout: float = _COMMAND_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    except FileNotFoundError as exc:
        raise ServiceError(f"'{cmd[0]}' was not found.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ServiceError(f"'{' '.join(cmd)}' did not finish within {int(timeout)} s.") from exc


def _launchctl_ok(*args: str) -> None:
    result = _run([LAUNCHCTL, *args])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        log.error("❌ launchctl failed — HiroServer · service", command=f"launchctl {' '.join(args)}", error=detail)
        raise ServiceError(f"`launchctl {' '.join(args)}` failed: {detail}")


def service_state(label: str) -> ServiceState:
    """Ask launchd about the service (no root needed for a system service's state)."""
    require_mac()
    result = _run([LAUNCHCTL, "print", service_target(label)])
    if result.returncode == _NOT_FOUND or (result.returncode != 0 and "could not find" in result.stderr.lower()):
        return ServiceState(label=label, installed=False, plist_path=None)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ServiceError(f"Could not read the state of {label}: {detail}")
    state = parse_print_output(label, result.stdout)
    state.plist_path = state.plist_path or plist_path(label)
    return state


def install_service(spec: LaunchdSpec) -> Path:
    """Write the plist, load it into launchd (which starts it: RunAtLoad), and return the plist's path.

    Safe to run again: a loaded service is taken out first, so the new plist is the one that runs.
    """
    require_mac()
    if os.geteuid() != 0:
        raise ServiceError("Installing a LaunchDaemon must run as root.")
    path = plist_path(spec.label)
    tmp = path.with_suffix(".plist.tmp")
    try:
        tmp.write_bytes(render_plist(spec))
        os.chown(tmp, 0, 0)  # root:wheel: launchd refuses a daemon's plist owned by anyone else
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        log.error("❌ Could not write the LaunchDaemon — HiroServer · service", path=str(path), error=str(exc))
        raise ServiceError(f"Could not write {path}: {exc}") from exc
    if service_state(spec.label).installed:
        _launchctl_ok("bootout", service_target(spec.label))
    _launchctl_ok("bootstrap", DOMAIN, str(path))
    _launchctl_ok("enable", service_target(spec.label))
    log.info("✅ Service installed — HiroServer · service", service=spec.label, user=spec.user, plist=str(path))
    return path


def start_service(label: str) -> None:
    require_mac()
    _launchctl_ok("kickstart", service_target(label))


def stop_service(label: str) -> None:
    """Ask the program to stop (SIGTERM). It exits with 0, so KeepAlive leaves it stopped until the next start."""
    require_mac()
    _launchctl_ok("kill", "SIGTERM", service_target(label))


def uninstall_service(label: str) -> bool:
    """Take the service out of launchd and delete its plist; return False when it wasn't installed."""
    require_mac()
    if os.geteuid() != 0:
        raise ServiceError("Removing a LaunchDaemon must run as root.")
    path = plist_path(label)
    loaded = service_state(label).installed
    if not loaded and not path.exists():
        return False
    if loaded:
        _launchctl_ok("bootout", service_target(label))
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise ServiceError(f"Could not delete {path}: {exc}") from exc
    log.info("✅ Service removed — HiroServer · service", service=label)
    return True
