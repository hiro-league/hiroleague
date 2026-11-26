"""An installed app on the system: the elevated part that makes and removes its account and service, and the core's own
start and stop through the one right that part gives it (the design's §6 and §8).

**Elevated** (``hiro extension system <job>``, one sudo or Windows prompt a person approves; never the core): it
checks its job (domain/system_job.py), finds the account the core runs as from the core's own service, and on
install makes, for the app ``hiro-<key, dashed>``:

- **Linux:** the account; ``<home>/apps/<key>`` (the core's, readable by all), its ``data/`` (the app's, in the core's
  group, setgid, so both may write what either makes there: the unit's ``UMask=0007``); the unit
  ``/etc/systemd/system/hiro-<..>.service`` (``EnvironmentFile=`` app.env, read by systemd as root); a polkit rule that
  lets the core's account start, stop and restart that one unit. Enabled, not started.
- **Windows:** the service under WinSW (its virtual account ``NT SERVICE\\hiro-<..>``) from ``apps\\<key>\\service``;
  the folder for the core (change) and the app (read; ``data\\`` change); the service's permissions let the core's
  account start and stop it. Not started.
- **Mac (untried):** the account; a LaunchDaemon that sources app.env through ``/bin/sh`` (a plist is world-readable);
  a sudoers line that lets the core's account load and unload that one daemon.

On remove it takes all of that away again, and with ``purge`` the app's folder too.

**The core** (its own account, no admin): it unpacks releases, writes app.env and, on Windows, the WinSW
configuration in ``service\\`` (the program and environment the service runs), then starts and stops the service
(`start`, `stop`, `state`).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from hiro_commons.log import Logger
from hiro_commons.systemd_service import ServiceError, ServiceSpec, render_unit

from .domain.hiro_home import APPS
from .domain.system_job import INSTALL, AppSystem, JobRefused

log = Logger.get("CLI.APP_SYSTEM")

CORE_SERVICE = "hiro"  # the core's own service (the default workspace's): its account is the one given the right
_TIMEOUT_S = 120


@dataclass(frozen=True)
class SystemDone:
    """What the elevated part did, for the person and the core."""

    action: str
    key: str
    service: str
    account: str
    core_account: str
    folder: str
    purged: bool = False


def _run(cmd: list[str], what: str, *, ok_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(  # noqa: S603 — fixed system programs, no shell
            cmd, capture_output=True, text=True, timeout=_TIMEOUT_S, check=False, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ServiceError(f"{what} failed: {exc}") from exc
    if result.returncode not in ok_codes:
        detail = " | ".join((result.stderr or result.stdout).strip().splitlines()[-3:])
        log.error("❌ An app's system command failed — HiroServer · extension", command=" ".join(cmd), error=detail)
        raise ServiceError(f"{what} failed: {detail or f'exit code {result.returncode}'}")
    return result


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(mode)
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ServiceError(f"Could not write {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Linux: an account, a unit, a polkit rule
# ---------------------------------------------------------------------------

UNIT_DIR = PurePosixPath("/etc/systemd/system")
POLKIT_DIR = PurePosixPath("/etc/polkit-1/rules.d")


def linux_unit_path(service: str) -> PurePosixPath:
    return UNIT_DIR / f"{service}.service"


def polkit_rule_path(service: str) -> PurePosixPath:
    return POLKIT_DIR / f"60-{service}.rules"


def polkit_rule(service: str, core_user: str) -> str:
    """The core's account may start, stop and restart this one unit, and nothing else (polkit 0.106 and later: Simone
    runs 124)."""
    for value in (service, core_user):
        if not re.fullmatch(r"[a-z_][a-z0-9_-]*", value):
            raise JobRefused(f"{value!r} can't be named in a polkit rule.")
    return (
        f"// {service}: written by `hiro extension system` (Hiro League). The core's account ({core_user}) may start,\n"
        f"// stop and restart this one app's service; removing the app removes this file.\n"
        "polkit.addRule(function(action, subject) {\n"
        '    if (action.id == "org.freedesktop.systemd1.manage-units" &&\n'
        f'        action.lookup("unit") == "{service}.service" &&\n'
        f'        subject.user == "{core_user}" &&\n'
        '        ["start", "stop", "restart"].indexOf(action.lookup("verb")) >= 0) {\n'
        "        return polkit.Result.YES;\n"
        "    }\n"
        "});\n"
    )


def linux_unit(app: AppSystem, core_group: str) -> str:
    folder = app.folder
    spec = ServiceSpec(
        name=app.service,
        description=f"Hiro League app {app.key}",
        user=app.account,
        group=core_group,
        exec_args=[str(PurePosixPath(folder.current.as_posix()) / "bin" / app.command)],
        env_file=Path(folder.env_file.as_posix()),
        umask="0007",
    )
    return render_unit(spec)


def linux_core_user() -> str:
    """The account the core's own service runs as; JobRefused when the core isn't installed as a service."""
    out = _run(["systemctl", "show", "-p", "User", "--value", f"{CORE_SERVICE}.service"], "Reading the core's service")
    user = out.stdout.strip()
    if not user or user == "root":
        raise JobRefused("The core isn't installed as a service here (hiro service install): an app has no core to "
                         "start it.")
    return user


def install_linux(app: AppSystem) -> SystemDone:
    import grp
    import pwd

    core_user = linux_core_user()
    core = pwd.getpwnam(core_user)
    core_group = grp.getgrgid(core.pw_gid).gr_name
    folder = app.folder
    try:
        pwd.getpwnam(app.account)
    except KeyError:
        _run(["useradd", "--system", "--user-group", "--no-create-home", "--home-dir", str(folder.data),
              "--shell", "/usr/sbin/nologin", "--comment", f"Hiro League app {app.key}", app.account],
             f"Creating the account {app.account}")
    account = pwd.getpwnam(app.account)
    apps = folder.home / APPS
    for path in (apps, folder.root, folder.releases):
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, core.pw_uid, core.pw_gid)
        path.chmod(0o755)
    folder.data.mkdir(parents=True, exist_ok=True)
    # Its data folder and, when an earlier install's data was kept (remove without --purge), everything in it: a new
    # account has a new uid, and the files would stay the old one's
    for path in (folder.data, *folder.data.rglob("*")):
        os.chown(path, account.pw_uid, core.pw_gid, follow_symlinks=False)
    folder.data.chmod(0o2770)  # setgid: what either makes there stays in the core's group
    _write(Path(str(linux_unit_path(app.service))), linux_unit(app, core_group))
    _write(Path(str(polkit_rule_path(app.service))), polkit_rule(app.service, core_user))
    _run(["systemctl", "daemon-reload"], "Reloading systemd")
    _run(["systemctl", "enable", f"{app.service}.service"], f"Enabling {app.service}")
    log.info("✅ An app's account and service made — HiroServer · extension", key=app.key, service=app.service,
             core=core_user)
    return SystemDone(action=INSTALL, key=app.key, service=f"{app.service}.service", account=app.account,
                      core_account=core_user, folder=str(folder.root))


def remove_linux(app: AppSystem, purge: bool) -> SystemDone:
    unit = Path(str(linux_unit_path(app.service)))
    if unit.exists():
        _run(["systemctl", "disable", "--now", f"{app.service}.service"], f"Stopping {app.service}", ok_codes=(0, 1, 5))
        unit.unlink()
    Path(str(polkit_rule_path(app.service))).unlink(missing_ok=True)
    _run(["systemctl", "daemon-reload"], "Reloading systemd")
    if purge and app.folder.root.exists():
        shutil.rmtree(app.folder.root)
    _run(["userdel", app.account], f"Removing the account {app.account}", ok_codes=(0, 6))  # 6: no such user
    log.info("✅ An app's account and service removed — HiroServer · extension", key=app.key, purged=purge)
    return SystemDone(action="remove", key=app.key, service=f"{app.service}.service", account=app.account,
                      core_account="", folder=str(app.folder.root), purged=purge)


# ---------------------------------------------------------------------------
# Windows: WinSW, a virtual account, the service's own permissions
# ---------------------------------------------------------------------------

# Start, stop, read the state and the configuration: the right the core gets on the app's service (SDDL)
CORE_SERVICE_RIGHTS = "RPWPLCLORC"


def windows_spec(app: AppSystem, environment: dict[str, str] | None = None):
    """The app's WinSW configuration: written once by the elevated part (no environment, to register the service), then
    by the core each time it writes app.env (WinSW has no environment file)."""
    from hiro_commons.winsw_service import WinswSpec

    folder = app.folder
    return WinswSpec(
        id=app.service,
        name=f"Hiro League app {app.key}",
        description=f"The Hiro League app {app.key}, installed by the core.",
        executable=folder.current / "bin" / f"{app.command}.exe",  # uv tool install's command (UV_TOOL_BIN_DIR)
        arguments=[],
        working_directory=folder.data,
        log_dir=folder.data / "service-logs",
        environment={"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(environment or {})},
    )


def with_core_ace(sddl: str, sid: str) -> str:
    """The service's permissions (SDDL) with an entry that lets ``sid`` start and stop it, before any audit part."""
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise ServiceError(f"{sid!r} isn't an account's SID.")
    ace = f"(A;;{CORE_SERVICE_RIGHTS};;;{sid})"
    if ace in sddl:
        return sddl
    head, sep, audit = sddl.partition("S:")
    return f"{head}{ace}{sep}{audit}"


def _service_sid(name: str) -> str:
    out = _run(["sc.exe", "showsid", name], f"Reading the SID of {name}").stdout
    match = re.search(r"SERVICE SID:\s*(S-1-[0-9-]+)", out)
    if not match:
        raise ServiceError(f"Windows didn't say the SID of the service {name}.")
    return match[1]


def windows_core_account() -> tuple[str, str]:
    """The core's own service account and its SID; JobRefused when the core isn't installed as a service."""
    from hiro_commons.winsw_service import service_state

    state = service_state(CORE_SERVICE)
    if not state.installed:
        raise JobRefused("The core isn't installed as a service here (hiro service install): an app has no core to "
                         "start it.")
    return state.account or f"NT SERVICE\\{CORE_SERVICE}", _service_sid(CORE_SERVICE)


def install_windows(app: AppSystem) -> SystemDone:
    from hiro_commons.winsw_service import install_service, lock_folder

    account, sid = windows_core_account()
    folder = app.folder
    apps = folder.home / APPS
    apps.mkdir(parents=True, exist_ok=True)
    # The core makes each app's release and environment here: apps\ is its to change (its own account, by name)
    _run(["icacls", str(apps), "/grant", f"{account}:(OI)(CI)M"], f"Letting the core change {apps}")
    for path in (folder.root, folder.releases, folder.data):
        path.mkdir(parents=True, exist_ok=True)
    _home_uv(folder.home)
    install_service(windows_spec(app), folder.service_dir)  # the app's virtual account exists from here on
    lock_folder(folder.root, service_id=app.service, service_rights="RX")
    _run(["icacls", str(folder.root), "/grant", f"{account}:(OI)(CI)M"], f"Letting the core change {folder.root}")
    _run(["icacls", str(folder.data), "/grant", f"NT SERVICE\\{app.service}:(OI)(CI)M"],
         f"Letting {app.service} change its data")
    sddl = _run(["sc.exe", "sdshow", app.service], f"Reading {app.service}'s permissions").stdout.strip()
    _run(["sc.exe", "sdset", app.service, with_core_ace(sddl, sid)], f"Letting the core start {app.service}")
    log.info("✅ An app's service made — HiroServer · extension", key=app.key, service=app.service, core=account)
    return SystemDone(action=INSTALL, key=app.key, service=app.service, account=f"NT SERVICE\\{app.service}",
                      core_account=account, folder=str(folder.root))


def _home_uv(home: Path) -> None:
    """The core unpacks an app's release with uv: a service core has no PATH of the person's, so the Hiro home keeps
    its own copy (``<home>/bin/uv.exe``), taken from this person's uv once."""
    target = home / "bin" / "uv.exe"
    if target.is_file():
        return
    found = shutil.which("uv")
    if not found:
        raise ServiceError("uv isn't on this PATH: install uv (https://docs.astral.sh/uv/), then install the app again.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(found, target)
    log.info("The Hiro home has its own uv now — HiroServer · extension", path=str(target))


def remove_windows(app: AppSystem, purge: bool) -> SystemDone:
    from hiro_commons.winsw_service import remove_service

    remove_service(app.service)
    if purge and app.folder.root.exists():
        shutil.rmtree(app.folder.root)
    log.info("✅ An app's service removed — HiroServer · extension", key=app.key, purged=purge)
    return SystemDone(action="remove", key=app.key, service=app.service, account=f"NT SERVICE\\{app.service}",
                      core_account="", folder=str(app.folder.root), purged=purge)


# ---------------------------------------------------------------------------
# Mac: a LaunchDaemon and a sudoers line (untried: no Mac yet)
# ---------------------------------------------------------------------------

MAC_DAEMONS = PurePosixPath("/Library/LaunchDaemons")
SUDOERS_DIR = PurePosixPath("/etc/sudoers.d")


def mac_label(app: AppSystem) -> str:
    return f"com.hiroleague.app.{app.service.removeprefix('hiro-')}"


def mac_plist(app: AppSystem) -> str:
    from xml.sax.saxutils import escape

    folder = app.folder
    program = str(PurePosixPath(folder.current.as_posix()) / "bin" / app.command)
    # The environment comes from app.env, which only the core and the app read: a plist is world-readable
    script = f"set -a; . '{folder.env_file.as_posix()}'; set +a; exec '{program}'"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f"  <key>Label</key><string>{escape(mac_label(app))}</string>\n"
        f"  <key>UserName</key><string>{escape(app.account)}</string>\n"
        "  <key>ProgramArguments</key><array><string>/bin/sh</string><string>-c</string>"
        f"<string>{escape(script)}</string></array>\n"
        f"  <key>WorkingDirectory</key><string>{escape(folder.data.as_posix())}</string>\n"
        "  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n"
        f"  <key>StandardErrorPath</key><string>{escape((folder.data / 'service.log').as_posix())}</string>\n"
        "</dict></plist>\n"
    )


def mac_sudoers(app: AppSystem, core_user: str) -> str:
    plist = MAC_DAEMONS / f"{mac_label(app)}.plist"
    return (
        f"# {app.service}: written by `hiro extension system` (Hiro League); the core loads and unloads this one app.\n"
        f"{core_user} ALL=(root) NOPASSWD: /bin/launchctl bootstrap system {plist}, "
        f"/bin/launchctl bootout system/{mac_label(app)}\n"
    )


# ---------------------------------------------------------------------------
# The elevated entry, and the core's own start and stop
# ---------------------------------------------------------------------------


def apply(app: AppSystem, action: str, *, purge: bool = False) -> SystemDone:
    """Do the job on this system (elevated)."""
    if sys.platform == "win32":
        return install_windows(app) if action == INSTALL else remove_windows(app, purge)
    if sys.platform == "darwin":
        raise ServiceError("Installing and removing an app on a Mac is built but not tried yet: no Mac to try it on.")
    return install_linux(app) if action == INSTALL else remove_linux(app, purge)


def write_windows_environment(app: AppSystem, environment: dict[str, str]) -> None:
    """The core writes the app's WinSW configuration with its environment (Windows: WinSW has no environment file)."""
    from hiro_commons.winsw_service import config_path, render_config

    _write(config_path(app.folder.service_dir, app.service), render_config(windows_spec(app, environment)))


def start(service: str) -> None:
    """Start the app's service with the core's own right (no admin)."""
    if sys.platform == "win32":
        from hiro_commons.winsw_service import start_service

        start_service(service)
    else:
        _run(["systemctl", "start", f"{service}.service"], f"Starting {service}")


def stop(service: str) -> None:
    if sys.platform == "win32":
        from hiro_commons.winsw_service import stop_service

        stop_service(service)
    else:
        _run(["systemctl", "stop", f"{service}.service"], f"Stopping {service}")


def is_running(service: str) -> bool | None:
    """Whether the app's service runs (None: the system doesn't know it)."""
    if sys.platform == "win32":
        from hiro_commons.winsw_service import service_state

        state = service_state(service)
        return None if not state.installed else state.state == "RUNNING"
    from hiro_commons.systemd_service import service_state as unit_state

    unit = unit_state(service)
    return None if not unit.installed else unit.active_state == "active"
