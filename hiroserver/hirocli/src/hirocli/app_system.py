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
- **Mac:** the account and its group (hidden, ids 400 to 499); ``<home>/apps/<key>`` (the core's), which the app may
  read (an inherited ACL entry: it reads app.env itself); its ``data/`` (the app's), which both may change (inherited
  ACL entries for both accounts: the core's account is a person's, in ``staff``, so no shared group); a LaunchDaemon,
  not loaded, that sources app.env through ``/bin/sh`` (a plist is world-readable); a sudoers line that lets the
  core's account load and unload that one daemon (``launchctl bootstrap`` / ``bootout``: a system daemon's start
  and stop need root).

On remove it takes all of that away again, and with ``purge`` the app's folder too.

**The core** (its own account, no admin): it unpacks releases, writes app.env and, on Windows, the WinSW
configuration in ``service\\`` (the program and environment the service runs), then starts and stops the service
(`start`, `stop`, `state`).
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from hiro_commons.fetch import shared_downloads
from hiro_commons.log import Logger
from hiro_commons.systemd_service import ServiceError, ServiceSpec, render_unit

from .domain.hiro_home import APPS
from .domain.system_job import INSTALL, AppSystem, JobRefused
from .windows_service import copy_uv_into

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
    kept: str = ""  # what the step left on purpose, in words for the person (a Mac account macOS won't let it remove)


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
    copy_uv_into(folder.home)
    # The app's virtual account exists from here on. Its WinSW comes from the downloads folder: the core's service
    # left one there, and each app downloaded its own (17 MB from GitHub, most of an app's install in the test)
    install_service(windows_spec(app), folder.service_dir, downloads=shared_downloads(folder.home))
    lock_folder(folder.root, service_id=app.service, service_rights="RX")
    _run(["icacls", str(folder.root), "/grant", f"{account}:(OI)(CI)M"], f"Letting the core change {folder.root}")
    _run(["icacls", str(folder.data), "/grant", f"NT SERVICE\\{app.service}:(OI)(CI)M"],
         f"Letting {app.service} change its data")
    sddl = _run(["sc.exe", "sdshow", app.service], f"Reading {app.service}'s permissions").stdout.strip()
    _run(["sc.exe", "sdset", app.service, with_core_ace(sddl, sid)], f"Letting the core start {app.service}")
    log.info("✅ An app's service made — HiroServer · extension", key=app.key, service=app.service, core=account)
    return SystemDone(action=INSTALL, key=app.key, service=app.service, account=f"NT SERVICE\\{app.service}",
                      core_account=account, folder=str(folder.root))


def _writable_then_again(func: Callable[..., object], path: str, exc: BaseException) -> None:
    """rmtree's retry for a read-only file, which Windows won't delete."""
    if isinstance(exc, FileNotFoundError):
        return
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_windows(app: AppSystem, purge: bool) -> SystemDone:
    from hiro_commons.winsw_service import remove_service

    remove_service(app.service)
    if purge and app.folder.root.exists():
        # Fix (Installing apps phase 6, Nov 27): an app's read-only files (git writes its packs so: CodeHiro's
        # mirrors) refused the purge with "Access is denied" on Windows. They are made writable and removed.
        shutil.rmtree(app.folder.root, onexc=_writable_then_again)
    log.info("✅ An app's service removed — HiroServer · extension", key=app.key, purged=purge)
    return SystemDone(action="remove", key=app.key, service=app.service, account=f"NT SERVICE\\{app.service}",
                      core_account="", folder=str(app.folder.root), purged=purge)


# ---------------------------------------------------------------------------
# Mac: a hidden account, ACL entries, a LaunchDaemon and a sudoers line
# ---------------------------------------------------------------------------

MAC_DAEMONS = PurePosixPath("/Library/LaunchDaemons")
SUDOERS_DIR = PurePosixPath("/etc/sudoers.d")
LAUNCHCTL = "/bin/launchctl"
SUDO = "/usr/bin/sudo"
DSCL = "/usr/bin/dscl"
VISUDO = "/usr/sbin/visudo"
# Hidden service accounts: below 500, so never in the sign-in window; macOS's own take most ids below 300
MAC_IDS = range(400, 500)
_MAC_STOP_WAIT_S = 75  # a daemon's ExitTimeOut (60 s: launchd's SIGKILL after it), and a margin
_DS_REFUSED = 40  # dscl's exit code when Directory Services refuses (eDSPermissionError, and other errors)
# What each account may do in a folder, and what everything made in it inherits (macOS's ACL names; a folder's list,
# add_file, search and add_subdirectory are a file's read, write, execute and append)
_READS = "list,search,readattr,readextattr,readsecurity"
_CHANGES = ("list,add_file,search,add_subdirectory,delete,delete_child,readattr,writeattr,readextattr,writeextattr,"
            "readsecurity")
_INHERIT = "file_inherit,directory_inherit"
_MAC_NAME = re.compile(r"[a-z_][a-z0-9_-]*")


def mac_label(service: str) -> str:
    """The app's LaunchDaemon: ``com.hiroleague.app.<key, dashed>`` (beside the core's ``com.hiroleague.hiro``)."""
    return f"com.hiroleague.app.{service.removeprefix('hiro-')}"


def mac_plist_path(service: str) -> PurePosixPath:
    return MAC_DAEMONS / f"{mac_label(service)}.plist"


def mac_sudoers_path(service: str) -> PurePosixPath:
    return SUDOERS_DIR / service  # no dot in the name: sudo skips such files in sudoers.d


def mac_plist(app: AppSystem) -> bytes:
    """The app's LaunchDaemon, as the core's own (``launchd_service``: restarted after a crash, a clean exit stays
    stopped), run as the app's account; it reads app.env itself, since a plist is world-readable."""
    from hiro_commons.launchd_service import LaunchdSpec, render_plist

    folder = app.folder
    program = str(PurePosixPath(folder.current.as_posix()) / "bin" / app.command)
    # Paths are quoted for /bin/sh: a key has no quote (the key rule), the Hiro home has a space
    script = f"set -a; . '{folder.env_file.as_posix()}'; set +a; exec '{program}'"
    return render_plist(LaunchdSpec(
        label=mac_label(app.service),
        user=app.account,
        program_args=["/bin/sh", "-c", script],
        working_directory=Path(folder.data.as_posix()),
        log_path=Path((folder.data / "service.log").as_posix()),
        environment={"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
    ))


def mac_sudoers(app: AppSystem, core_user: str) -> str:
    """The core's account may load and unload this one app's daemon, with exactly these arguments, and nothing else."""
    for value in (app.service, core_user):
        if not _MAC_NAME.fullmatch(value):
            raise JobRefused(f"{value!r} can't be named in a sudoers line.")
    return (
        f"# {app.service}: written by `hiro extension system` (Hiro League); the core loads and unloads this one app.\n"
        f"{core_user} ALL=(root) NOPASSWD: {LAUNCHCTL} bootstrap system {mac_plist_path(app.service)}, "
        f"{LAUNCHCTL} bootout system/{mac_label(app.service)}\n"
    )


def mac_ace(account: str, rights: str) -> str:
    """One inherited ACL entry for ``chmod +a``."""
    return f"user:{account} allow {rights},{_INHERIT}"


def free_mac_id(used: set[int]) -> int:
    """The first id in MAC_IDS that no account and no group has (the app's account and its group share it)."""
    for n in MAC_IDS:
        if n not in used:
            return n
    raise ServiceError(f"No id is free for the app's account ({MAC_IDS.start} to {MAC_IDS.stop - 1} are all taken).")


def mac_core_user() -> str:
    """The account the core's own LaunchDaemon runs as; JobRefused when the core isn't installed as a service."""
    import plistlib

    from hiro_commons.launchd_service import plist_path

    from .mac_service import label

    path = plist_path(label(None))
    try:
        with path.open("rb") as fh:
            user = str(plistlib.load(fh).get("UserName", ""))
    except FileNotFoundError:
        user = ""
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ServiceError(f"The core's service ({path}) can't be read: {exc}") from exc
    if not user or user == "root":
        raise JobRefused("The core isn't installed as a service here (hiro service install): an app has no core to "
                         "start it.")
    return user


def _mac_used_ids() -> set[int]:
    used: set[int] = set()
    for kind, attribute in (("/Users", "UniqueID"), ("/Groups", "PrimaryGroupID")):
        for line in _run([DSCL, ".", "-list", kind, attribute], "Reading the Mac's accounts").stdout.splitlines():
            last = line.split()[-1] if line.split() else ""
            if last.lstrip("-").isdigit():
                used.add(int(last))
    return used


def _mac_account(app: AppSystem) -> None:
    """The app's hidden account and its own group, with no password and no shell; kept when it exists."""
    import grp
    import pwd

    try:
        pwd.getpwnam(app.account)
        return
    except KeyError:
        pass  # not made yet: made below
    n = str(free_mac_id(_mac_used_ids()))
    name, real = app.account, f"Hiro League app {app.key}"
    try:
        grp.getgrnam(name)
    except KeyError:
        group = f"/Groups/{name}"
        for args in ([], ["PrimaryGroupID", n], ["RealName", real], ["Password", "*"]):
            _run([DSCL, ".", "-create", group, *args], f"Creating the group {name}")
    user = f"/Users/{name}"
    gid = str(grp.getgrnam(name).gr_gid)
    for args in ([], ["UniqueID", n], ["PrimaryGroupID", gid], ["UserShell", "/usr/bin/false"],
                 ["NFSHomeDirectory", app.folder.data.as_posix()], ["RealName", real], ["IsHidden", "1"],
                 ["Password", "*"]):
        _run([DSCL, ".", "-create", user, *args], f"Creating the account {name}")


def _mac_acl(path: Path, *entries: str, recursive: bool = False) -> None:
    """``path``'s ACL is exactly these entries (an earlier install's, an old account's, are taken away first)."""
    flag = ["-R"] if recursive else []
    _run(["/bin/chmod", *flag, "-N", str(path)], f"Clearing the ACL of {path}")
    for entry in entries:
        _run(["/bin/chmod", *flag, "+a", entry, str(path)], f"Setting the ACL of {path}")


def _write_sudoers(app: AppSystem, core_user: str) -> None:
    """The sudoers line, checked by visudo before it is put in place: a broken file there would break sudo."""
    path = Path(str(mac_sudoers_path(app.service)))
    tmp = path.with_name(f".{path.name}.tmp")  # a dot in the name: sudo never reads it
    try:
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        tmp.write_text(mac_sudoers(app, core_user), encoding="utf-8")
        tmp.chmod(0o440)
        _run([VISUDO, "-cf", str(tmp)], "Checking the sudoers line")
        tmp.replace(path)
    except OSError as exc:
        raise ServiceError(f"Could not write {path}: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)


def install_mac(app: AppSystem) -> SystemDone:
    import pwd

    core_user = mac_core_user()
    core = pwd.getpwnam(core_user)
    _mac_account(app)
    account = pwd.getpwnam(app.account)
    folder = app.folder
    apps = folder.home / APPS
    for path in (apps, folder.root, folder.releases):
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, core.pw_uid, core.pw_gid)
        path.chmod(0o755)
    # The app reads its folder: app.env, which the core writes 0600 (the pairing code) and the app's /bin/sh sources
    _mac_acl(folder.root, mac_ace(app.account, _READS))
    folder.data.mkdir(parents=True, exist_ok=True)
    # Its data folder and, when an earlier install's data was kept (remove without --purge), everything in it: a new
    # account has a new uid, and the files would stay the old one's
    for path in (folder.data, *folder.data.rglob("*")):
        os.chown(path, account.pw_uid, account.pw_gid, follow_symlinks=False)
    folder.data.chmod(0o770)
    # Both may change what either makes there: the core copies and puts back the data in an upgrade
    _mac_acl(folder.data, mac_ace(app.account, _CHANGES), mac_ace(core_user, _CHANGES), recursive=True)
    plist = Path(str(mac_plist_path(app.service)))
    _write(plist, mac_plist(app).decode("utf-8"))  # by root, 0644: launchd refuses a daemon's plist anyone else owns
    _write_sudoers(app, core_user)
    log.info("✅ An app's account and service made — HiroServer · extension", key=app.key,
             service=mac_label(app.service), core=core_user)
    return SystemDone(action=INSTALL, key=app.key, service=mac_label(app.service), account=app.account,
                      core_account=core_user, folder=str(folder.root))


def remove_mac(app: AppSystem, purge: bool) -> SystemDone:
    import grp
    import pwd

    from hiro_commons.launchd_service import service_state

    label = mac_label(app.service)
    if service_state(label).installed:
        _run([LAUNCHCTL, "bootout", f"system/{label}"], f"Stopping {label}")
        _mac_wait_gone(label)
    Path(str(mac_plist_path(app.service))).unlink(missing_ok=True)
    Path(str(mac_sudoers_path(app.service))).unlink(missing_ok=True)
    if purge and app.folder.root.exists():
        shutil.rmtree(app.folder.root)
    refused = [kind for kind, exists in (("Users", pwd.getpwnam), ("Groups", grp.getgrnam))
               if _has(exists, app.account) and not _mac_delete(kind, app.account)]
    kept = ""
    if refused:
        # Fix (Nov 27, the Mac test VM): macOS lets only a program with its "administer files" right (Full Disk
        # Access, or the person's yes to its prompt) delete an account; over SSH it refuses, where making one works.
        # The account stays, hidden, with no password and no shell, and nothing runs as it; an install reuses it.
        kept = (f"macOS didn't let it remove the account {app.account} (hidden, no password, nothing runs as it; an "
                f"install uses it again). To remove it: give Terminal Full Disk Access (System Settings → Privacy & "
                f"Security), then `sudo dscl . -delete /Users/{app.account}` and "
                f"`sudo dscl . -delete /Groups/{app.account}`.")
        log.warning("⚠️ An app's account kept — HiroServer · extension: macOS refused to delete it", key=app.key,
                    account=app.account, records=",".join(refused))
    log.info("✅ An app's account and service removed — HiroServer · extension", key=app.key, purged=purge)
    return SystemDone(action="remove", key=app.key, service=label, account=app.account, core_account="",
                      folder=str(app.folder.root), purged=purge, kept=kept)


def _has(lookup: Callable[[str], object], name: str) -> bool:
    try:
        lookup(name)
    except KeyError:
        return False
    return True


def _mac_delete(kind: str, name: str) -> bool:
    """Delete a user or group record; False when macOS's privacy control refuses it (eDSPermissionError)."""
    done = _run([DSCL, ".", "-delete", f"/{kind}/{name}"], f"Removing the account {name}", ok_codes=(0, _DS_REFUSED))
    if done.returncode == 0:
        return True
    if "eDSPermissionError" not in (done.stderr + done.stdout):
        raise ServiceError(f"Removing the account {name} failed: {(done.stderr or done.stdout).strip()}")
    return False


def _launchctl(*args: str) -> None:
    """launchctl as root: through the sudoers line for the core's account (``-n``: never a password prompt)."""
    _run([LAUNCHCTL, *args] if os.geteuid() == 0 else [SUDO, "-n", LAUNCHCTL, *args], f"launchctl {args[0]}")


def _mac_start(service: str) -> None:
    from hiro_commons.launchd_service import service_state

    label = mac_label(service)
    state = service_state(label)
    if state.installed and state.state == "running":
        return
    if state.installed:  # loaded but stopped (a clean exit, or waiting to restart): load it again
        _launchctl("bootout", f"system/{label}")
        _mac_wait_gone(label)
    _launchctl("bootstrap", "system", str(mac_plist_path(service)))


def _mac_stop(service: str) -> None:
    from hiro_commons.launchd_service import service_state

    label = mac_label(service)
    if service_state(label).installed:
        _launchctl("bootout", f"system/{label}")
        _mac_wait_gone(label)


def _mac_wait_gone(label: str) -> None:
    """Until launchd no longer knows the daemon: its process has exited. Fix (Nov 27, the Mac test VM): bootout
    returns while the app is still stopping ("SIGTERMed"), and an upgrade copies its data right after the stop."""
    import time

    from hiro_commons.launchd_service import service_state

    deadline = time.monotonic() + _MAC_STOP_WAIT_S
    while service_state(label).installed:
        if time.monotonic() > deadline:
            raise ServiceError(f"{label} didn't stop within {_MAC_STOP_WAIT_S} s.")
        time.sleep(0.25)


def _mac_running(service: str) -> bool | None:
    """Made means its plist is there (launchd loads it at boot and at the core's start, and the core's stop unloads
    it); running is launchd's word."""
    from hiro_commons.launchd_service import service_state

    if not Path(str(mac_plist_path(service))).exists():
        return None
    state = service_state(mac_label(service))
    return state.installed and state.state == "running"


# ---------------------------------------------------------------------------
# The elevated entry, and the core's own start and stop
# ---------------------------------------------------------------------------


def apply(app: AppSystem, action: str, *, purge: bool = False) -> SystemDone:
    """Do the job on this system (elevated)."""
    if sys.platform == "win32":
        return install_windows(app) if action == INSTALL else remove_windows(app, purge)
    if sys.platform == "darwin":
        return install_mac(app) if action == INSTALL else remove_mac(app, purge)
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
    elif sys.platform == "darwin":
        _mac_start(service)
    else:
        _run(["systemctl", "start", f"{service}.service"], f"Starting {service}")


def stop(service: str) -> None:
    if sys.platform == "win32":
        from hiro_commons.winsw_service import stop_service

        stop_service(service)
    elif sys.platform == "darwin":
        _mac_stop(service)
    else:
        _run(["systemctl", "stop", f"{service}.service"], f"Stopping {service}")


def is_running(service: str) -> bool | None:
    """Whether the app's service runs (None: the system doesn't know it)."""
    if sys.platform == "win32":
        from hiro_commons.winsw_service import service_state

        state = service_state(service)
        return None if not state.installed else state.state == "RUNNING"
    if sys.platform == "darwin":
        return _mac_running(service)
    from hiro_commons.systemd_service import service_state as unit_state

    unit = unit_state(service)
    return None if not unit.installed else unit.active_state == "active"
