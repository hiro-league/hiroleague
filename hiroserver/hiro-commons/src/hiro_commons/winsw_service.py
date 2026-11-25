"""Windows service support for Hiro executables, through WinSW: install, remove, start, stop and read its state.

``python.exe`` is not a service program (it doesn't answer the service manager), so a Hiro server runs as a Windows
service under WinSW, a small wrapper that is one: the service manager starts WinSW, WinSW starts the program and keeps
it. What WinSW 2.12.0 does, read in its source at the tag (``src/WinSW/WrapperService.cs``):

- the program exits by itself with 0: WinSW reports the service stopped, and it stays stopped;
- it exits with anything else (75 included, a crash, a kill): WinSW exits with that code without reporting a stop, so
  the service manager runs the service's failure actions, which restart it (``<onfailure>``; the last one repeats);
- a stop sends Ctrl+C to the program, waits ``<stoptimeout>``, then kills the whole process tree;
- ``<serviceaccount>`` with no password installs it as a virtual account (``NT SERVICE\\<id>``), which Windows makes
  when the service is registered: no password, no admin rights.

Each service gets its own copy of WinSW, named after the service, with its configuration beside it
(``<id>.exe`` + ``<id>.xml``). Installing, removing, starting and stopping a service need an administrator; the caller
checks :func:`is_admin` first (:class:`NeedsAdminError`).

Rendering and parsing are pure so they can be unit-tested anywhere; everything that touches the system is
Windows-only.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from xml.sax.saxutils import escape, quoteattr

from .fetch import FetchError, fetch_checked
from .log import Logger
# One error type for every system's service, so a caller catches the same one on Linux, Windows and Mac.
from .systemd_service import ServiceError

log = Logger.get("SERVICE")

# The WinSW release every Hiro service runs, reviewed on Nov 25, 2026: 2.12.0 (Jan 2023), not the 2.13/2.14 line
# released in Nov 2026 (three releases in ten days, the newest with no files). GitHub publishes no digest for 2.12.0;
# this SHA-256 is the one Scoop recorded when it was released (ScoopInstaller/Main, bucket/winsw.json, commit
# 5ea81de9, Jan 28, 2023), and the file downloaded on Nov 25, 2026 matched it. Changing the release means a new review.
WINSW_VERSION = "2.12.0"
WINSW_URL = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"
WINSW_SHA256 = "05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da"

SC = "sc.exe"
ICACLS = "icacls.exe"
# Well-known SIDs, so the grants work on a Windows in any language.
SID_SYSTEM = "*S-1-5-18"
SID_ADMINISTRATORS = "*S-1-5-32-544"
SID_USERS = "*S-1-5-32-545"
VIRTUAL_ACCOUNT_DOMAIN = "NT SERVICE"

_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COMMAND_TIMEOUT_S = 120
_ERROR_SERVICE_DOES_NOT_EXIST = 1060
_ERROR_CANCELLED = 1223  # the person said No to the UAC prompt


class NeedsAdminError(ServiceError):
    """The operation registers or changes a service and must run as an administrator."""

    def __init__(self, action: str, command: str) -> None:
        self.action = action
        self.command = command
        super().__init__(
            f"{action} needs an administrator: Windows only lets one register or change a service. "
            f"Run it from an administrator terminal:\n  {command}"
        )


@dataclass(frozen=True)
class WinswSpec:
    """Everything a WinSW configuration needs. ``executable`` must be an absolute path."""

    id: str
    name: str
    description: str
    executable: Path
    arguments: list[str]
    working_directory: Path
    log_dir: Path
    environment: dict[str, str] = field(default_factory=dict)
    # How long a stop waits for the program after Ctrl+C before killing it (the systemd unit's TimeoutStopSec).
    stop_timeout_s: int = 60
    # The wait before the service manager starts it again (the systemd unit's RestartSec).
    restart_delay_s: int = 5

    @property
    def account(self) -> str:
        return f"{VIRTUAL_ACCOUNT_DOMAIN}\\{self.id}"


@dataclass
class ServiceState:
    """What the service manager reports about a service (``installed`` False when it doesn't know it)."""

    name: str
    installed: bool
    state: str = "unknown"  # RUNNING, STOPPED, START_PENDING...
    pid: int | None = None
    start_type: str = ""  # AUTO_START (DELAYED), DEMAND_START...
    account: str = ""
    binary_path: str = ""
    exit_code: int | None = None


# ---------------------------------------------------------------------------
# Names and paths
# ---------------------------------------------------------------------------


def validate_id(name: str) -> str:
    if not name or not _ID_RE.match(name) or len(name) > 80:
        raise ServiceError(f"'{name}' is not a valid service name: use letters, digits, '-', '_' or '.'.")
    return name


def wrapper_path(service_dir: Path, service_id: str) -> Path:
    """Where the service's own copy of WinSW lives; its configuration is the same name with ``.xml``."""
    return service_dir / f"{validate_id(service_id)}.exe"


def config_path(service_dir: Path, service_id: str) -> Path:
    return service_dir / f"{validate_id(service_id)}.xml"


# ---------------------------------------------------------------------------
# Rendering and parsing (pure)
# ---------------------------------------------------------------------------


def _no_percent(label: str, value: str) -> str:
    # WinSW expands %NAME% in its settings: a literal '%' would start the program with another value.
    if "%" in value:
        raise ServiceError(f"{label} must not contain '%' (WinSW would read it as a variable): {value}")
    return value


def render_config(spec: WinswSpec) -> str:
    """Return the WinSW configuration text for ``spec``."""
    validate_id(spec.id)
    if not PureWindowsPath(spec.executable).is_absolute():
        raise ServiceError("The service's program must be an absolute path.")
    arguments = subprocess.list2cmdline(spec.arguments)
    lines = [
        f"<!-- {spec.id}.xml: written by `hiro service install`. Run that again to change it; edits here are lost. -->",
        "<service>",
        f"  <id>{escape(spec.id)}</id>",
        f"  <name>{escape(spec.name)}</name>",
        f"  <description>{escape(spec.description)}</description>",
        f"  <executable>{escape(_no_percent('The program path', str(spec.executable)))}</executable>",
        f"  <arguments>{escape(_no_percent('The arguments', arguments))}</arguments>",
        f"  <workingdirectory>{escape(_no_percent('The working folder', str(spec.working_directory)))}</workingdirectory>",
    ]
    for key, value in spec.environment.items():
        if not _ENV_NAME_RE.match(key):
            raise ServiceError(f"'{key}' is not a valid environment variable name.")
        lines.append(f"  <env name={quoteattr(key)} value={quoteattr(_no_percent(key, value))}/>")
    lines += [
        # A virtual account: Windows makes NT SERVICE\<id> when the service is registered; no password.
        "  <serviceaccount>",
        f"    <domain>{VIRTUAL_ACCOUNT_DOMAIN}</domain>",
        f"    <user>{escape(spec.id)}</user>",
        "  </serviceaccount>",
        # Starts at boot with nobody signed in; delayed, so the network is up when the server starts.
        "  <startmode>Automatic</startmode>",
        "  <delayedAutoStart>true</delayedAutoStart>",
        # Any exit but 0 is a failure, and every failure restarts it (the last action repeats).
        f'  <onfailure action="restart" delay="{spec.restart_delay_s} sec"/>',
        "  <resetfailure>1 hour</resetfailure>",
        f"  <stoptimeout>{spec.stop_timeout_s} sec</stoptimeout>",
        f"  <logpath>{escape(_no_percent('The log folder', str(spec.log_dir)))}</logpath>",
        '  <log mode="roll-by-size">',
        "    <sizeThreshold>10240</sizeThreshold>",
        "    <keepFiles>8</keepFiles>",
        "  </log>",
        "</service>",
        "",
    ]
    return "\n".join(lines)


def _fields(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().isupper():
            out[key.strip()] = value.strip()
    return out


def parse_sc_output(name: str, queryex: str, qc: str) -> ServiceState:
    """Turn ``sc.exe queryex <name>`` and ``sc.exe qc <name>`` output into a :class:`ServiceState`."""
    q = _fields(queryex)
    c = _fields(qc)
    state_words = q.get("STATE", "").split()
    pid_text = q.get("PID", "0")
    pid = int(pid_text) if pid_text.isdigit() and int(pid_text) > 0 else None
    exit_words = q.get("WIN32_EXIT_CODE", "").split()
    start_words = c.get("START_TYPE", "").split()
    return ServiceState(
        name=name,
        installed=True,
        state=state_words[1] if len(state_words) > 1 else "unknown",
        pid=pid,
        start_type=" ".join(start_words[1:]) if len(start_words) > 1 else "",
        account=c.get("SERVICE_START_NAME", ""),
        binary_path=c.get("BINARY_PATH_NAME", "").strip('"'),
        exit_code=int(exit_words[0]) if exit_words and exit_words[0].isdigit() else None,
    )


# ---------------------------------------------------------------------------
# System access (Windows only)
# ---------------------------------------------------------------------------


def require_windows() -> None:
    if sys.platform != "win32":
        raise ServiceError("This is the Windows service; this system is not Windows.")


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except OSError:
        # The call itself failed: treat as not elevated, so the caller asks for elevation instead of failing later.
        log.warning("⚠️ Could not tell whether this terminal is elevated — HiroServer · service", exc_info=True)
        return False


def filesystem_of(path: Path) -> str:
    """The file system of the drive ``path`` is on (``NTFS``, ``exFAT``, ``FAT32``, ``ReFS``...)."""
    require_windows()
    root = Path(path.resolve().anchor)
    name = ctypes.create_unicode_buffer(64)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(  # type: ignore[attr-defined]
        str(root), None, 0, None, None, None, name, len(name)
    )
    if not ok:
        raise ServiceError(f"Could not read the file system of {root} (is the drive there?).")
    return name.value


def require_permissions_disk(path: Path, label: str) -> None:
    """Refuse a folder on a disk with no permissions (FAT, exFAT): the family's data would be open to every account."""
    fs = filesystem_of(path)
    if fs.upper() not in ("NTFS", "REFS"):
        raise ServiceError(
            f"{label} {path} is on a {fs} disk, which has no permissions: every account on this PC could read "
            "it, the family's data included. Choose a folder on an NTFS disk."
        )


def _run(cmd: list[str], *, timeout: float = _COMMAND_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 — fixed programs (sc.exe, icacls.exe, the service's WinSW), no shell
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as exc:
        raise ServiceError(f"'{cmd[0]}' was not found.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ServiceError(f"'{' '.join(cmd)}' did not finish within {int(timeout)} s.") from exc


def _run_ok(cmd: list[str], what: str) -> subprocess.CompletedProcess[str]:
    result = _run(cmd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        log.error("❌ A service command failed — HiroServer · service", command=" ".join(cmd), error=" | ".join(detail))
        raise ServiceError(f"{what} failed: {' '.join(detail) or f'exit code {result.returncode}'}")
    return result


def lock_folder(path: Path, *, service_id: str, service_rights: str) -> None:
    """Give ``path`` (and what it holds) its own permissions: SYSTEM and administrators in full, the service with
    ``service_rights`` (``M`` change, ``RX`` read and run), nobody else. Inherited permissions are dropped."""
    account = f"{VIRTUAL_ACCOUNT_DOMAIN}\\{validate_id(service_id)}"
    _run_ok(
        [
            ICACLS, str(path), "/inheritance:r",
            "/grant:r", f"{SID_SYSTEM}:(OI)(CI)F",
            "/grant:r", f"{SID_ADMINISTRATORS}:(OI)(CI)F",
            "/grant:r", f"{account}:(OI)(CI){service_rights}",
        ],
        f"Setting the permissions of {path}",
    )


def lock_program_folder(path: Path) -> None:
    """The program folder: everyone may read and run it, only administrators may change it (a planted file there
    would run as the service)."""
    _run_ok(
        [
            ICACLS, str(path), "/inheritance:r",
            "/grant:r", f"{SID_SYSTEM}:(OI)(CI)F",
            "/grant:r", f"{SID_ADMINISTRATORS}:(OI)(CI)F",
            "/grant:r", f"{SID_USERS}:(OI)(CI)RX",
        ],
        f"Setting the permissions of {path}",
    )


def grant_read(path: Path, *, service_id: str) -> None:
    """Let the service read and run what ``path`` holds, by name: a virtual account's membership of Users is not
    something to count on."""
    account = f"{VIRTUAL_ACCOUNT_DOMAIN}\\{validate_id(service_id)}"
    _run_ok([ICACLS, str(path), "/grant", f"{account}:(OI)(CI)RX"], f"Letting the service read {path}")


def lock_file(path: Path, *, service_id: str) -> None:
    """A secrets file: SYSTEM and administrators in full, the service may read it, nobody else."""
    account = f"{VIRTUAL_ACCOUNT_DOMAIN}\\{validate_id(service_id)}"
    _run_ok(
        [
            ICACLS, str(path), "/inheritance:r",
            "/grant:r", f"{SID_SYSTEM}:F",
            "/grant:r", f"{SID_ADMINISTRATORS}:F",
            "/grant:r", f"{account}:R",
        ],
        f"Setting the permissions of {path}",
    )


def fetch_wrapper(dest: Path) -> bool:
    """Put the pinned WinSW at ``dest`` (checked against its SHA-256); True when it was downloaded."""
    try:
        return fetch_checked(WINSW_URL, dest, WINSW_SHA256)
    except FetchError as exc:
        # Already logged where it failed; the caller shows a service error's words to the person.
        raise ServiceError(str(exc)) from exc


def service_state(name: str) -> ServiceState:
    """Ask the service manager about the service (no administrator needed)."""
    require_windows()
    validate_id(name)
    queryex = _run([SC, "queryex", name])
    if queryex.returncode == _ERROR_SERVICE_DOES_NOT_EXIST:
        return ServiceState(name=name, installed=False)
    if queryex.returncode != 0:
        detail = (queryex.stderr or queryex.stdout).strip()
        raise ServiceError(f"Could not read the state of the service {name}: {detail}")
    qc = _run([SC, "qc", name])
    return parse_sc_output(name, queryex.stdout, qc.stdout if qc.returncode == 0 else "")


def wait_for_state(name: str, wanted: str, *, timeout_s: float = 90.0) -> ServiceState:
    """Wait until the service reports ``wanted`` (RUNNING, STOPPED); raise when it doesn't in time."""
    deadline = time.monotonic() + timeout_s
    state = service_state(name)
    while state.state != wanted and time.monotonic() < deadline:
        time.sleep(1.0)
        state = service_state(name)
    if state.state != wanted:
        raise ServiceError(f"The service {name} is {state.state}, not {wanted}, after {int(timeout_s)} s.")
    return state


def _wrapper(wrapper: Path, command: str, what: str) -> None:
    _run_ok([str(wrapper), command], what)


def install_service(spec: WinswSpec, service_dir: Path) -> None:
    """Write the service's WinSW and configuration, register the service, and leave it stopped.

    A service already registered under this name is stopped and removed first, so installing again picks up the new
    configuration. The caller starts it once the folders it needs have their permissions (the account exists only
    from here on).
    """
    require_windows()
    if not is_admin():
        raise ServiceError("Installing a Windows service must run as an administrator.")
    service_dir.mkdir(parents=True, exist_ok=True)
    wrapper = wrapper_path(service_dir, spec.id)
    fetch_wrapper(wrapper)
    if service_state(spec.id).installed:
        remove_service(spec.id)
    xml = config_path(service_dir, spec.id)
    tmp = xml.with_suffix(".xml.tmp")
    try:
        tmp.write_text(render_config(spec), encoding="utf-8")
        os.replace(tmp, xml)
    except OSError as exc:
        log.error("❌ Could not write the service configuration — HiroServer · service", path=str(xml), error=str(exc))
        raise ServiceError(f"Could not write {xml}: {exc}") from exc
    _wrapper(wrapper, "install", f"Registering the service {spec.id}")
    log.info("✅ Service registered — HiroServer · service", service=spec.id, account=spec.account, config=str(xml))


def start_service(name: str) -> ServiceState:
    """Start the service and wait until it runs; a running one is left as it is."""
    require_windows()
    state = service_state(name)
    if state.state == "RUNNING":
        return state
    _run_ok([SC, "start", name], f"Starting the service {name}")
    return wait_for_state(name, "RUNNING")


def stop_service(name: str) -> ServiceState:
    """Stop the service and wait until it has; a stopped one is left as it is."""
    require_windows()
    state = service_state(name)
    if not state.installed or state.state == "STOPPED":
        return state
    _run_ok([SC, "stop", name], f"Stopping the service {name}")
    # The stop timeout in the configuration (60 s) plus the time to report it.
    return wait_for_state(name, "STOPPED", timeout_s=90.0)


def remove_service(name: str) -> bool:
    """Stop the service and unregister it; return False when it wasn't installed. Files are kept."""
    require_windows()
    if not is_admin():
        raise ServiceError("Removing a Windows service must run as an administrator.")
    state = service_state(name)
    if not state.installed:
        return False
    stop_service(name)
    _run_ok([SC, "delete", name], f"Removing the service {name}")
    deadline = time.monotonic() + 30.0
    while service_state(name).installed and time.monotonic() < deadline:
        time.sleep(0.5)
    log.info("✅ Service removed — HiroServer · service", service=name)
    return True


# ---------------------------------------------------------------------------
# Elevation
# ---------------------------------------------------------------------------


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 — ctypes' own declaration
        ("cbSize", ctypes.c_uint32),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_uint32),
        ("hIconOrMonitor", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


class ElevationRefused(ServiceError):
    """The person said No to the administrator prompt."""


def run_elevated(args: list[str], *, cwd: Path | None = None) -> int:
    """Run ``args`` as an administrator (one UAC prompt), wait for it, and return its exit code.

    The elevated program opens its own window, so its output doesn't come back here: the caller passes it a file to
    write its outcome to.
    """
    require_windows()
    see_mask_nocloseprocess = 0x40
    sw_shownormal = 1
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = see_mask_nocloseprocess
    info.lpVerb = "runas"
    info.lpFile = args[0]
    info.lpParameters = subprocess.list2cmdline(args[1:])
    info.lpDirectory = str(cwd) if cwd else None
    info.nShow = sw_shownormal
    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error() or kernel32.GetLastError()
        if error == _ERROR_CANCELLED:
            raise ElevationRefused("The administrator prompt was declined, so nothing was changed.")
        raise ServiceError(f"Could not start an administrator terminal (Windows error {error}).")
    try:
        infinite = 0xFFFFFFFF
        kernel32.WaitForSingleObject(info.hProcess, infinite)
        code = ctypes.c_uint32()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return int(code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)
