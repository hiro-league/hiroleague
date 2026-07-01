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
DEVICE_ID_PREFIX: str = "mobile-"
DEVICE_ID_SUFFIX_LENGTH: int = 12
