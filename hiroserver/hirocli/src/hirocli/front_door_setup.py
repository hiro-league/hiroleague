"""The front door's one-time setup, run inside `hiro service install` with the admin rights that step already has.

The core never holds admin rights (design: "the core never holds admin rights"), so everything the front door needs
from the system is made here, once: Caddy's program (fetched, its checksum checked: hirocli/caddy_release.py), its
account and service, its right to port 80 and the firewall rules. The core's service is then given where Caddy's
admin API listens (``HIRO_FRONT_DOOR``) and loads every name through it (runtime/site_names.py).

Caddy starts with the admin API only (``initial.json``) and binds port 80 once the core loads what to serve; after
that it brings back its last configuration by itself (``--resume``, its autosave), with or without the core.

- **Linux:** account ``hiro-caddy``; admin API on ``/run/hiro-caddy/admin.sock``, which the core's account opens
  through the ``hiro-caddy`` group the setup adds it to; port 80 through ``CAP_NET_BIND_SERVICE`` in Caddy's unit
  alone; no firewall rule.
- **Windows:** account ``NT SERVICE\\hiro-caddy`` under WinSW; admin API on ``127.0.0.1:18079`` (Caddy takes no
  socket on Windows); port 80 needs no right; firewall rules for TCP 80 (caddy.exe) and UDP 5353 (the core's Python).
- **Mac (untried):** the core's account; admin API on an owner-only socket in the Hiro home; port 80 needs no root
  since Mojave; no firewall rule.
"""

from __future__ import annotations

import dataclasses
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from hiro_commons.log import Logger
from hiro_commons.systemd_service import ServiceError, ServiceUser, quote_exec_arg

from .caddy_release import CADDY_VERSION, fetch_caddy
from .domain.front_door import initial_config, parse_admin

log = Logger.get("CLI.FRONT_DOOR")

SERVICE = "hiro-caddy"  # the service's and the account's name on every system
DESCRIPTION = "Hiro League front door (Caddy)"
DOCS_URL = "https://docs.hiroleague.com/hiro/get-started/linux-service"
_TIMEOUT_S = 120


@dataclass(frozen=True)
class FrontDoorSetup:
    """What the setup made: what the core's service is given, and what to tell the person."""

    admin: str  # HIRO_FRONT_DOOR: Caddy's admin address as Caddy writes it
    program: str
    service: str
    account: str
    firewall: list[str] = dataclasses.field(default_factory=list)  # the rules added (Windows)


def _run(cmd: list[str], what: str, *, ok_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(  # noqa: S603 — fixed system programs, no shell
            cmd, capture_output=True, text=True, timeout=_TIMEOUT_S, check=False, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ServiceError(f"{what} failed: {exc}") from exc
    if result.returncode not in ok_codes:
        detail = " | ".join((result.stderr or result.stdout).strip().splitlines()[-3:])
        log.error("❌ A front door setup command failed — HiroServer · service", command=" ".join(cmd), error=detail)
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


def run_args(program: Path | PurePosixPath, initial: Path | PurePosixPath) -> list[str]:
    """Caddy's command line: its last configuration (autosave) if it has one, else the admin API alone."""
    return [str(program), "run", "--resume", "--config", str(initial)]


# ---------------------------------------------------------------------------
# Linux: a systemd unit, its own account, the capability to bind port 80
# ---------------------------------------------------------------------------

LINUX_HOME = PurePosixPath("/opt/hiroleague/caddy")  # the Hiro home's caddy/ (Simone's release folder's sibling)
LINUX_SOCKET = PurePosixPath("/run/hiro-caddy/admin.sock")
LINUX_ADMIN = f"unix/{LINUX_SOCKET}|0660"  # Caddy's default is 0200, the owner alone; the group lets the core in
LINUX_UNIT = PurePosixPath(f"/etc/systemd/system/{SERVICE}.service")


def render_linux_unit(program: PurePosixPath, home: PurePosixPath = LINUX_HOME) -> str:
    exec_start = " ".join(quote_exec_arg(a) for a in run_args(program, home / "initial.json"))
    return "\n".join([
        f"# {SERVICE}.service: written by `hiro service install`. Run that again to change it; edits here are lost.",
        "[Unit]",
        f"Description={DESCRIPTION}",
        f"Documentation={DOCS_URL}",
        "Wants=network-online.target",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=notify",
        f"User={SERVICE}",
        f"Group={SERVICE}",
        # Where Caddy keeps its autosave (what the core last loaded) and its own state.
        f"Environment=XDG_CONFIG_HOME={home / 'config'}",
        f"Environment=XDG_DATA_HOME={home / 'data'}",
        f"ExecStart={exec_start}",
        # The admin socket's folder, made at each start: Caddy's account and the hiro-caddy group (the core) only.
        f"RuntimeDirectory={SERVICE}",
        "RuntimeDirectoryMode=0750",
        # Port 80 without root: this unit alone has the right, never the core.
        "AmbientCapabilities=CAP_NET_BIND_SERVICE",
        "CapabilityBoundingSet=CAP_NET_BIND_SERVICE",
        "NoNewPrivileges=true",
        "ProtectSystem=full",
        "PrivateTmp=true",
        "LimitNOFILE=1048576",
        "Restart=on-failure",
        "RestartSec=5",
        "TimeoutStopSec=10",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])


def install_linux(core_user: ServiceUser) -> FrontDoorSetup:
    """Caddy as ``hiro-caddy.service``; the core's account joins the ``hiro-caddy`` group to open its socket."""
    import grp
    import os
    import pwd

    home = Path(str(LINUX_HOME))
    try:
        pwd.getpwnam(SERVICE)
    except KeyError:
        _run(["useradd", "--system", "--user-group", "--no-create-home", "--home-dir", "/nonexistent",
              "--shell", "/usr/sbin/nologin", "--comment", DESCRIPTION, SERVICE], f"Creating the account {SERVICE}")
    caddy = pwd.getpwnam(SERVICE)
    if core_user.name not in grp.getgrnam(SERVICE).gr_mem:
        _run(["usermod", "--append", "--groups", SERVICE, core_user.name],
             f"Letting {core_user.name} reach the front door")
    program = fetch_caddy(home)  # root's: only this step changes it
    _write(home / "initial.json", initial_config(parse_admin(LINUX_ADMIN)))
    for folder in (home / "config", home / "data"):
        folder.mkdir(parents=True, exist_ok=True)
        os.chown(folder, caddy.pw_uid, caddy.pw_gid)
        folder.chmod(0o700)
    _write(Path(str(LINUX_UNIT)), render_linux_unit(PurePosixPath(program.as_posix())))
    _run(["systemctl", "daemon-reload"], "Reloading systemd")
    _run(["systemctl", "enable", f"{SERVICE}.service"], f"Enabling {SERVICE}")
    _run(["systemctl", "restart", f"{SERVICE}.service"], f"Starting {SERVICE}")
    log.info("✅ Front door installed — HiroServer · service", service=SERVICE, version=CADDY_VERSION)
    return FrontDoorSetup(admin=LINUX_ADMIN, program=str(program), service=f"{SERVICE}.service", account=SERVICE)


def uninstall_linux() -> bool:
    """Stop and remove Caddy's service and account; its folder (program, autosave) stays. False: not installed."""
    unit = Path(str(LINUX_UNIT))
    if not unit.exists():
        return False
    _run(["systemctl", "disable", "--now", f"{SERVICE}.service"], f"Stopping {SERVICE}")
    unit.unlink()
    _run(["systemctl", "daemon-reload"], "Reloading systemd")
    _run(["userdel", SERVICE], f"Removing the account {SERVICE}", ok_codes=(0, 6))  # 6: no such user
    return True


# ---------------------------------------------------------------------------
# Windows: under WinSW like the core, its own virtual account, two firewall rules
# ---------------------------------------------------------------------------

WINDOWS_ADMIN = "127.0.0.1:18079"  # below the workspaces' ports (18080 and up)
RULE_CADDY = "Hiro League front door (Caddy, TCP 80)"
RULE_NAMES = "Hiro League names (the core, UDP 5353)"


def _netsh_rule(name: str, program: Path, protocol: str, port: int) -> None:
    # Delete first: netsh adds a second rule of the same name rather than replacing it. 1: there was none.
    _run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"], f"Clearing the rule {name}",
         ok_codes=(0, 1))
    _run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}", "dir=in", "action=allow",
          f"program={program}", f"protocol={protocol}", f"localport={port}", "profile=any", "enable=yes"],
         f"Adding the firewall rule {name}")


def install_windows(home: Path, core_python: Path) -> FrontDoorSetup:
    """Caddy under WinSW as ``NT SERVICE\\hiro-caddy``; the firewall lets the LAN reach Caddy on TCP 80 and the
    core's Python answer name queries on UDP 5353 (Windows' own mDNS rule admits only its DNS Client)."""
    from hiro_commons.winsw_service import WinswSpec, grant_read, install_service, lock_folder, start_service

    caddy_home = home / "caddy"
    program = fetch_caddy(caddy_home)
    initial = caddy_home / "initial.json"
    _write(initial, initial_config(parse_admin(WINDOWS_ADMIN)))
    spec = WinswSpec(
        id=SERVICE,
        name=DESCRIPTION,
        description="Sends each name the Hiro League core serves on port 80 to its app on this machine.",
        executable=program,
        arguments=run_args(program, initial)[1:],
        working_directory=caddy_home,
        log_dir=caddy_home / "logs",
        environment={"XDG_CONFIG_HOME": str(caddy_home / "config"), "XDG_DATA_HOME": str(caddy_home / "data")},
        stop_timeout_s=15,
    )
    install_service(spec, home / "service")
    # The account exists from here on: it reads its program, and only it (and administrators) touch its state.
    grant_read(caddy_home, service_id=SERVICE)
    for folder in (caddy_home / "config", caddy_home / "data", caddy_home / "logs"):
        folder.mkdir(parents=True, exist_ok=True)
        lock_folder(folder, service_id=SERVICE, service_rights="M")
    _netsh_rule(RULE_CADDY, program, "TCP", 80)
    _netsh_rule(RULE_NAMES, core_python, "UDP", 5353)
    start_service(SERVICE)
    log.info("✅ Front door installed — HiroServer · service", service=SERVICE, version=CADDY_VERSION,
             python=str(core_python))
    return FrontDoorSetup(admin=WINDOWS_ADMIN, program=str(program), service=SERVICE,
                          account=spec.account, firewall=[RULE_CADDY, RULE_NAMES])


def uninstall_windows() -> bool:
    """Remove Caddy's service and both firewall rules; its folder stays. False: not installed."""
    from hiro_commons.winsw_service import remove_service

    removed = remove_service(SERVICE)
    for rule in (RULE_CADDY, RULE_NAMES):
        _run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rule}"], f"Removing the rule {rule}",
             ok_codes=(0, 1))
    return removed


# ---------------------------------------------------------------------------
# Mac: a LaunchDaemon (untried: no Mac yet)
# ---------------------------------------------------------------------------

MAC_LABEL = "com.hiroleague.caddy"


def mac_admin(home: Path) -> str:
    # Owner-only, Caddy's default: Caddy runs as the core's own account here.
    return f"unix/{(home / 'caddy' / 'run' / 'admin.sock').as_posix()}"


def install_mac(core_user: ServiceUser, home: Path) -> FrontDoorSetup:
    """Caddy as a LaunchDaemon under the core's account: a Mac binds port 80 without root, and an account of its own
    waits for a Mac to try it on (the plan's Later)."""
    import os

    from hiro_commons.launchd_service import LaunchdSpec, install_service

    caddy_home = home / "caddy"
    program = fetch_caddy(caddy_home)
    admin = mac_admin(home)
    initial = caddy_home / "initial.json"
    _write(initial, initial_config(parse_admin(admin)))
    for folder in (caddy_home / "config", caddy_home / "data", caddy_home / "run", caddy_home / "logs"):
        folder.mkdir(parents=True, exist_ok=True)
        os.chown(folder, core_user.uid, core_user.gid)
        folder.chmod(0o700)
    install_service(LaunchdSpec(
        label=MAC_LABEL,
        user=core_user.name,
        program_args=run_args(program, initial),
        working_directory=caddy_home,
        log_path=caddy_home / "logs" / "caddy.log",
        environment={"XDG_CONFIG_HOME": (caddy_home / "config").as_posix(),
                     "XDG_DATA_HOME": (caddy_home / "data").as_posix()},
        exit_timeout_s=15,
    ))
    log.info("✅ Front door installed — HiroServer · service", service=MAC_LABEL, version=CADDY_VERSION)
    return FrontDoorSetup(admin=admin, program=str(program), service=MAC_LABEL, account=core_user.name)


def uninstall_mac() -> bool:
    from hiro_commons.launchd_service import uninstall_service

    return uninstall_service(MAC_LABEL)


def which_python(release: Path) -> Path:
    """The Python program that runs the core of ``release``: the one that opens UDP 5353 (a uv tool's python.exe is
    a launcher that starts its base Python, which owns the socket)."""
    from .windows_service import python_home_of

    base = python_home_of(release)
    if base is None or not (base / "python.exe").is_file():
        raise ServiceError(f"Could not find the Python the service runs on in {release}; nothing was changed.")
    return base / "python.exe"

