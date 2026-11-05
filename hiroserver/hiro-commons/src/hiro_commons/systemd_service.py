"""Linux systemd service support for Hiro executables: install, remove, and read its state.

On Linux a Hiro server runs as a *system* service (``/etc/systemd/system/<name>.service``) so it
starts at boot with nobody signed in (a home server behind a login screen) and is restarted when it
fails. The pieces, all generic so any Hiro executable can use them:

- a unit file that runs the executable in the foreground as a chosen user;
- an environment file (``/etc/hiro/<name>.env``, mode 0600, owned by that user) that systemd loads
  into the service's environment, which is where provider API keys live on a server;
- install/uninstall/state helpers that call ``systemctl``.

The user the service runs as is always a parameter: a dedicated system user or the person's own
user are both supported, and nothing here assumes one or the other.

Installing or removing a system service writes under ``/etc`` and needs root. Callers check
:func:`is_root` first and tell the user the exact ``sudo`` command (:class:`NeedsRootError`).

Rendering (:func:`render_unit`, :func:`render_env_file`) is pure so it can be unit-tested anywhere;
everything that touches the system is Linux-only.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .log import Logger

log = Logger.get("SERVICE")

SYSTEMD_UNIT_DIR = Path("/etc/systemd/system")
ENV_FILE_DIR = Path("/etc/hiro")
SYSTEMCTL = "systemctl"
# keyring's "do nothing" backend: on a server there is no unlocked desktop keyring, and the default
# backend lookup can raise or hang. With it, secrets come from the environment file instead.
NULL_KEYRING_BACKEND = "keyring.backends.null.Keyring"
# How long the service user's check run of the executable may take (a cold Python start that
# imports the whole CLI can take tens of seconds on a small server).
_RUN_CHECK_TIMEOUT_SECONDS = 180
_SYSTEMCTL_TIMEOUT_SECONDS = 120

# systemd unit names: ASCII letters, digits and ":-_.\" (see systemd.unit(5)).
_UNIT_NAME_RE = re.compile(r"^[A-Za-z0-9:_.\-]+$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ServiceError(RuntimeError):
    """A service operation failed; the message says what happened and what to do."""


class NeedsRootError(ServiceError):
    """The operation writes system files and must run as root; ``command`` is what to run."""

    def __init__(self, action: str, command: str) -> None:
        self.action = action
        self.command = command
        super().__init__(
            f"{action} needs root: it writes the service under {SYSTEMD_UNIT_DIR} and "
            f"{ENV_FILE_DIR}, and asks systemd to load it. Run:\n  {command}"
        )


@dataclass(frozen=True)
class ServiceUser:
    """The account a service runs as (resolved from the system's user database)."""

    name: str
    uid: int
    gid: int
    group: str
    home: Path


@dataclass(frozen=True)
class ServiceSpec:
    """Everything a unit file needs. ``exec_args[0]`` must be an absolute path."""

    name: str
    description: str
    user: str
    group: str
    exec_args: list[str]
    env_file: Path
    environment: dict[str, str] = field(default_factory=dict)
    # Exit status the program uses to ask for a fresh start: systemd restarts it on that status
    # whatever Restart= says (the server's "restart" button can't spawn its own successor under
    # systemd, which would kill it with the rest of the service).
    restart_exit_code: int | None = None
    documentation: str | None = None


@dataclass
class ServiceState:
    """What systemd reports about a unit (``installed`` False when systemd doesn't know it)."""

    name: str
    installed: bool
    active_state: str = "unknown"
    sub_state: str = ""
    enabled_state: str = ""
    main_pid: int | None = None
    active_since: datetime | None = None
    user: str = ""
    restarts: int | None = None
    unit_path: Path | None = None
    env_file: Path | None = None


# ---------------------------------------------------------------------------
# Names and paths
# ---------------------------------------------------------------------------


def validate_unit_name(name: str) -> str:
    if not name or not _UNIT_NAME_RE.match(name):
        raise ServiceError(
            f"'{name}' is not a valid service name: use letters, digits, '-', '_', '.' or ':'."
        )
    return name


def unit_file_name(name: str) -> str:
    return f"{validate_unit_name(name)}.service"


def unit_path(name: str) -> Path:
    return SYSTEMD_UNIT_DIR / unit_file_name(name)


def env_file_path(name: str) -> Path:
    return ENV_FILE_DIR / f"{validate_unit_name(name)}.env"


# ---------------------------------------------------------------------------
# Rendering (pure)
# ---------------------------------------------------------------------------


def _escape_specifiers(value: str) -> str:
    # systemd expands %-specifiers and $VARS in ExecStart= and Environment=; a literal '%' or '$'
    # in a path or value must be doubled or the service starts with a different argument.
    return value.replace("%", "%%").replace("$", "$$")


def quote_exec_arg(arg: str) -> str:
    """Quote one ExecStart= argument the way systemd parses it."""
    escaped = _escape_specifiers(arg)
    if escaped and not re.search(r"[\s\"'\\;]", escaped):
        return escaped
    escaped = escaped.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _environment_line(key: str, value: str) -> str:
    if not _ENV_NAME_RE.match(key):
        raise ServiceError(f"'{key}' is not a valid environment variable name.")
    if "\n" in value:
        raise ServiceError(f"The value of {key} must be on one line.")
    escaped = _escape_specifiers(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'Environment="{key}={escaped}"'


def render_unit(spec: ServiceSpec) -> str:
    """Return the unit file text for ``spec``."""
    validate_unit_name(spec.name)
    # PurePosixPath: the unit is for Linux, whatever OS renders it (tests run on Windows too).
    if not spec.exec_args or not PurePosixPath(spec.exec_args[0]).is_absolute():
        raise ServiceError("The service's executable must be an absolute path.")
    if not spec.user or spec.user == "root":
        raise ServiceError("A Hiro service must run as a regular user, not root.")

    exec_start = " ".join(quote_exec_arg(a) for a in spec.exec_args)
    lines = [
        f"# {unit_file_name(spec.name)}: generated by `{Path(spec.exec_args[0]).name} service install`.",
        "# Re-run that command to change it; edits here are overwritten.",
        "[Unit]",
        f"Description={spec.description}",
    ]
    if spec.documentation:
        lines.append(f"Documentation={spec.documentation}")
    lines += [
        # Start once the network is up: the server talks to model providers and channels.
        "Wants=network-online.target",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"User={spec.user}",
        f"Group={spec.group}",
        # The user's home, not systemd's default "/", so nothing relative lands in the root folder.
        "WorkingDirectory=~",
        # Secrets (provider API keys). The leading '-' would ignore a missing file; we don't use
        # it, so a deleted secrets file is a clear start failure instead of a silent keyless run.
        f"EnvironmentFile={spec.env_file.as_posix()}",
    ]
    lines += [_environment_line(k, v) for k, v in spec.environment.items()]
    lines += [
        f"ExecStart={exec_start}",
        "Restart=on-failure",
        "RestartSec=5",
    ]
    if spec.restart_exit_code is not None:
        lines.append(f"RestartForceExitStatus={spec.restart_exit_code}")
    lines += [
        # SIGTERM goes to the server only, so it can stop its own child processes (channel
        # plugins) in order; anything still left after it exits is then killed.
        "KillMode=mixed",
        "TimeoutStopSec=60",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ]
    return "\n".join(lines)


def render_env_file(
    *,
    service_name: str,
    user: str,
    restart_command: str,
    sections: list[tuple[str, list[str]]],
) -> str:
    """Return the first version of a service's environment file.

    ``sections`` is a list of ``(heading, variable names)``; every variable is written commented
    out, ready to be filled in. The file is only written when missing, so the user's values are
    never overwritten.
    """
    lines = [
        f"# Environment for {unit_file_name(service_name)}: systemd reads it each time the service starts.",
        f"# Only {user} (the service's user) and root can read it (mode 0600). Keep it that way.",
        "# One VARIABLE=value per line; no quotes, no spaces around '='. Lines starting with # are ignored.",
        f"# After a change, restart the service: {restart_command}",
        "",
    ]
    for heading, names in sections:
        if not names:
            continue
        lines.append(f"# {heading}")
        lines += [f"# {name}=" for name in names]
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System access (Linux only)
# ---------------------------------------------------------------------------


def require_linux() -> None:
    if not sys.platform.startswith("linux"):
        raise ServiceError(
            "System services are only available on Linux (systemd). "
            "On Windows, Hiro starts at sign-in through auto-start instead."
        )


def is_root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0


def default_service_user() -> str:
    """The user running the install: the one who typed ``sudo`` when run through sudo."""
    sudo_user = os.environ.get("SUDO_USER")
    if is_root() and sudo_user and sudo_user != "root":
        return sudo_user
    import getpass

    return getpass.getuser()


def resolve_service_user(name: str) -> ServiceUser:
    """Look ``name`` up in the user database; refuse root and unknown users."""
    require_linux()
    import grp
    import pwd

    if name == "root":
        raise ServiceError(
            "The service must not run as root. Pass --user with a regular user, or create a "
            "dedicated one (e.g. `sudo useradd --system --create-home --home-dir /var/lib/hiro "
            "--shell /usr/sbin/nologin hiro`)."
        )
    try:
        pw = pwd.getpwnam(name)
    except KeyError as exc:
        raise ServiceError(
            f"There is no user '{name}' on this system. Create it first, for a dedicated user: "
            f"`sudo useradd --system --create-home --home-dir /var/lib/{name} "
            f"--shell /usr/sbin/nologin {name}`."
        ) from exc
    try:
        group = grp.getgrgid(pw.pw_gid).gr_name
    except KeyError:
        group = str(pw.pw_gid)
    home = Path(pw.pw_dir)
    if not home.is_dir():
        raise ServiceError(
            f"User '{name}' has no home folder ({home}); the service keeps its workspace there. "
            f"Create it (owned by {name}) or recreate the user with --create-home."
        )
    return ServiceUser(name=name, uid=pw.pw_uid, gid=pw.pw_gid, group=group, home=home)


def _run(cmd: list[str], *, timeout: float = _SYSTEMCTL_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ServiceError(
            f"'{cmd[0]}' was not found. Hiro services need a Linux system that uses systemd."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ServiceError(f"'{' '.join(cmd)}' did not finish within {int(timeout)} s.") from exc


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return _run([SYSTEMCTL, *args])


def _systemctl_ok(*args: str) -> None:
    result = _systemctl(*args)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        log.error(
            "❌ systemctl failed — HiroServer · service",
            command=f"systemctl {' '.join(args)}",
            error=detail,
        )
        raise ServiceError(f"`systemctl {' '.join(args)}` failed: {detail}")


def check_user_can_run(user: ServiceUser, exec_args: list[str]) -> None:
    """Run ``exec_args`` as ``user`` to prove the service will be able to start it.

    A program installed in someone's home folder (``~/.local/bin``) is usually not readable by
    another user (Ubuntu home folders are private), and its Python may live there too.
    """
    result = _run(["runuser", "-u", user.name, "--", *exec_args], timeout=_RUN_CHECK_TIMEOUT_SECONDS)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-5:])
        raise ServiceError(
            f"User '{user.name}' cannot run {exec_args[0]}:\n{tail}\n"
            "Install Hiro League where that user can read it (a shared folder such as /opt), "
            "or run the service as the user who installed it."
        )


def write_env_file(path: Path, content: str, user: ServiceUser) -> bool:
    """Create ``path`` (0600, owned by ``user``) unless it exists; return True when created.

    An existing file keeps its values; only its owner and mode are put right, since it holds
    secrets.
    """
    try:
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        created = False
        if not path.exists():
            # O_EXCL + 0600 at creation: the secrets file is never readable by others, not even
            # for the moment between writing it and changing its mode.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            created = True
        os.chown(path, user.uid, user.gid)
        os.chmod(path, 0o600)
        return created
    except OSError as exc:
        log.error("❌ Could not write the service environment file — HiroServer · service", path=str(path), error=str(exc))
        raise ServiceError(f"Could not write {path}: {exc}") from exc


def install_service(spec: ServiceSpec, user: ServiceUser, env_file_content: str, *, start: bool = True) -> bool:
    """Write the unit and env file, enable the service at boot and (re)start it.

    Returns True when the environment file was created (False: an existing one was kept).
    Safe to re-run: the unit is rewritten, the env file is kept.
    """
    require_linux()
    if not is_root():
        raise ServiceError("Installing a system service must run as root.")
    env_created = write_env_file(spec.env_file, env_file_content, user)
    path = unit_path(spec.name)
    try:
        path.write_text(render_unit(spec), encoding="utf-8")
        os.chmod(path, 0o644)
    except OSError as exc:
        log.error("❌ Could not write the unit file — HiroServer · service", path=str(path), error=str(exc))
        raise ServiceError(f"Could not write {path}: {exc}") from exc
    _systemctl_ok("daemon-reload")
    _systemctl_ok("enable", unit_file_name(spec.name))
    if start:
        # restart (not start): a re-install picks up the new unit right away.
        _systemctl_ok("restart", unit_file_name(spec.name))
    log.info(
        "✅ Service installed — HiroServer · service",
        service=unit_file_name(spec.name),
        user=spec.user,
        started=start,
        unit=str(path),
    )
    return env_created


def uninstall_service(name: str) -> bool:
    """Stop and disable the service and delete its unit; return False when it wasn't installed.

    The environment file is kept: it holds the user's secrets, and deleting it is their call.
    """
    require_linux()
    if not is_root():
        raise ServiceError("Removing a system service must run as root.")
    path = unit_path(name)
    if not path.exists():
        return False
    # disable --now stops it too; a unit that is already stopped is fine.
    _systemctl_ok("disable", "--now", unit_file_name(name))
    try:
        path.unlink()
    except OSError as exc:
        raise ServiceError(f"Could not delete {path}: {exc}") from exc
    _systemctl_ok("daemon-reload")
    log.info("✅ Service removed — HiroServer · service", service=unit_file_name(name))
    return True


def parse_show_output(name: str, text: str) -> ServiceState:
    """Turn ``systemctl show --timestamp=unix -p ...`` output into a :class:`ServiceState`."""
    props: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key.strip()] = value.strip()
    load_state = props.get("LoadState", "")
    installed = load_state not in ("", "not-found")
    pid_text = props.get("MainPID", "0")
    main_pid = int(pid_text) if pid_text.isdigit() and int(pid_text) > 0 else None
    since: datetime | None = None
    stamp = props.get("ActiveEnterTimestamp", "")
    if stamp.startswith("@") and stamp[1:].isdigit() and int(stamp[1:]) > 0:
        since = datetime.fromtimestamp(int(stamp[1:]), UTC)
    restarts_text = props.get("NRestarts", "")
    return ServiceState(
        name=name,
        installed=installed,
        active_state=props.get("ActiveState", "unknown") or "unknown",
        sub_state=props.get("SubState", ""),
        enabled_state=props.get("UnitFileState", ""),
        main_pid=main_pid,
        active_since=since,
        user=props.get("User", ""),
        restarts=int(restarts_text) if restarts_text.isdigit() else None,
        unit_path=Path(props["FragmentPath"]) if props.get("FragmentPath") else None,
    )


def service_state(name: str) -> ServiceState:
    """Ask systemd about the service (no root needed)."""
    require_linux()
    result = _systemctl(
        "show",
        unit_file_name(name),
        "--timestamp=unix",
        "-p",
        "LoadState,ActiveState,SubState,UnitFileState,MainPID,ActiveEnterTimestamp,User,NRestarts,FragmentPath",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ServiceError(f"Could not read the state of {unit_file_name(name)}: {detail}")
    state = parse_show_output(name, result.stdout)
    env_file = env_file_path(name)
    state.env_file = env_file if env_file.exists() else None
    return state
