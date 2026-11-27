"""What `hiro service` answers, the same on Linux (systemd), Windows (WinSW) and Mac (launchd)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ServiceInstallResult:
    service: str  # what the system calls it: hiro.service, hiro, com.hiroleague.hiro
    manager: str  # systemd | winsw | launchd
    user: str  # the account it runs as
    definition_path: str  # the unit file, the WinSW configuration, the plist
    secrets_file: str
    secrets_file_created: bool  # False: an existing secrets file was kept as it was
    exec_start: str
    started: bool
    edit_secrets: str  # how to add the provider keys
    restart_command: str  # how to load them
    logs: str  # where to read what the service prints
    data_dir: str | None = None  # Windows: the service's own data folder (HIRO_DATA_DIR)
    # The front door the install set up (the default service only: one per machine): its service, the account it runs
    # as, and the firewall rules added (Windows).
    front_door: str | None = None
    front_door_account: str | None = None
    firewall: list[str] = field(default_factory=list)
    front_door_names: str | None = None  # what announces the names on the LAN, or what to do for it (Linux)
    cpp_runtime: str | None = None  # Windows: Microsoft's C++ runtime, present, installed now, or what to do for it


@dataclass
class ServiceUninstallResult:
    service: str
    removed: bool  # False: it was not installed
    secrets_file: str | None  # secrets file left in place, if any
    kept: list[str] = field(default_factory=list)  # folders left in place (the data, the program)
    delete_secrets: str | None = None  # how to delete the secrets file, when one was left
    front_door_removed: bool = False  # the default service's uninstall removes the front door too


@dataclass
class ServiceStatusResult:
    service: str
    manager: str
    installed: bool
    running: bool
    state: str  # the system's own word: active, RUNNING, running
    detail: str  # systemd's sub-state, Windows' start type...
    at_boot: bool | None
    boot_detail: str
    main_pid: int | None
    active_since_iso: str | None
    user: str
    restarts: int | None
    definition_path: str | None
    secrets_file: str | None
    install_command: str  # what to run when it is not installed
    logs: str


@dataclass
class ServiceControlResult:
    service: str
    action: str  # started | stopped
    state: str
    main_pid: int | None
