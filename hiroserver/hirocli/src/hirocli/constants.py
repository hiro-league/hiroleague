"""Hiro package-local constants."""

from __future__ import annotations

from hiro_commons.constants.storage import RUN_DIR

APP_NAME: str = "hiro"
# Server pid lives under <workspace>/run/ alongside the other ephemeral process state.
# The subdir is baked into the filename so every read_pid/write_pid/remove_pid call site
# (which passes the workspace root as base_path) resolves to the same run/ location.
PID_FILENAME: str = f"{RUN_DIR}/server.pid"
# Renamed from HIRO_WORKSPACE
ENV_WORKSPACE: str = "HIRO_WORKSPACE"
# Renamed from HIRO_WORKSPACE_PATH
ENV_WORKSPACE_PATH: str = "HIRO_WORKSPACE_PATH"
# Renamed from HIRO_ADMIN_UI
ENV_ADMIN_UI: str = "HIRO_ADMIN_UI"
ENV_METRICS: str = "HIRO_METRICS"
ENV_HIRO_ENV: str = "HIRO_ENV"
# Set by `hiro service install` to the service manager that runs the server: "systemd" (Linux), "winsw" (Windows),
# "launchd" (Mac). Under any of them the server must not spawn its own successor on restart: the manager would not
# hold it (systemd and WinSW would even kill it with the old process).
ENV_SERVICE_MANAGER: str = "HIRO_SERVICE_MANAGER"
# Exit status meaning "start me again" (EX_TEMPFAIL): systemd's RestartForceExitStatus= matches it; WinSW and launchd
# restart on any exit but 0.
SERVICE_RESTART_EXIT_CODE: int = 75
# The service's secrets file (NAME=value lines), set where the server reads it itself (Windows and Mac; on Linux
# systemd loads it into the environment).
ENV_SECRETS_FILE: str = "HIRO_SECRETS_FILE"
# Where the workspace registry and the default workspaces live, instead of the account's own data folder. A Windows
# service sets it to its machine-wide data folder, so an administrator's `hiro` with the same setting reaches it.
ENV_DATA_DIR: str = "HIRO_DATA_DIR"
DEVICE_ID_PREFIX: str = "mobile-"
DEVICE_ID_SUFFIX_LENGTH: int = 12
