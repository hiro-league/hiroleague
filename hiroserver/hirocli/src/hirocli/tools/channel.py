"""Channel plugin management tools.

Six operations: list, install, setup, enable, disable, remove.
'channel status' (runtime connectivity query) is CLI/HTTP-only — it reads
ephemeral in-memory state, not persistent config, so it is not a tool.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME

from hiro_commons.process import find_workspace_root

from ..domain.channel_config import (
    ChannelConfig,
    delete_channel_config,
    list_channel_configs,
    load_channel_config,
    save_channel_config,
)
from ..domain.channel_descriptor import (
    coerce_and_validate_config,
    load_channel_descriptor,
    secret_keys,
)
from ..domain.channel_secret_store import SECRET_MARKER, ChannelSecretStore
from ..domain.features import feature_active
from ..domain.workspace import workspace_id_for_path
from ..domain.config import load_config, master_key_path
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ChannelListResult:
    channels: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ChannelInstallResult:
    package: str
    success: bool
    output: str


@dataclass
class ChannelSetupResult:
    name: str
    enabled: bool
    command: str
    workspace_dir: str


@dataclass
class ChannelEnableResult:
    name: str
    enabled: bool


@dataclass
class ChannelDisableResult:
    name: str
    enabled: bool


@dataclass
class ChannelRemoveResult:
    name: str
    removed: bool


@dataclass
class ChannelConfigResult:
    name: str
    config: dict[str, Any] = field(default_factory=dict)


def _parse_config_value(raw: str) -> Any:
    """Parse a CLI value: JSON when it parses (list/bool/int/…), else the raw string."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def _apply_secret_write(
    workspace_path: Path,
    channel_name: str,
    key: str,
    value: str | None,
    cfg: ChannelConfig,
) -> None:
    """Store a secret-declared config key in the keyring; keep only a marker in config (§5.6)."""
    wid = workspace_id_for_path(workspace_path)
    if wid is None:
        raise ValueError(
            "Cannot store a channel secret: this workspace is not in the registry."
        )
    store = ChannelSecretStore(workspace_path, wid)
    if value is None:
        store.delete(channel_name, key)
        cfg.config.pop(key, None)
    else:
        # value is the raw string as typed — secrets are never JSON-coerced.
        store.set(channel_name, key, value)
        cfg.config[key] = dict(SECRET_MARKER)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class ChannelListTool(Tool):
    name = "channel_list"
    description = "List all configured channel plugins and their enabled status"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> ChannelListResult:
        workspace_path = _resolve_path(workspace)
        configs = list_channel_configs(workspace_path)
        return ChannelListResult(
            channels=[
                {
                    "name": cfg.name,
                    "enabled": cfg.enabled,
                    "command": " ".join(cfg.effective_command()),
                    "config_keys": list(cfg.config.keys()),
                }
                for cfg in configs
            ]
        )


class ChannelInstallTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "channel_install"
    description = "Install a channel plugin package via uv tool install"
    params = {
        "channel_name": ToolParam(str, "Channel name, e.g. 'telegram'"),
        "package": ToolParam(str, "Package name override (default: hiro-channel-<name>)", required=False),
        "editable": ToolParam(bool, "Install in editable/development mode", required=False),
    }

    def execute(
        self,
        channel_name: str,
        package: str | None = None,
        editable: bool = False,
    ) -> ChannelInstallResult:
        pkg = package or f"hiro-channel-{channel_name}"
        cmd = ["uv", "tool", "install"]
        if editable:
            cmd.append("--editable")
        cmd.append(pkg)

        proc = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
        output = (proc.stdout or proc.stderr).strip()

        if proc.returncode != 0:
            raise RuntimeError(
                f"Install failed (exit {proc.returncode}): {proc.stderr.strip()}"
            )

        return ChannelInstallResult(package=pkg, success=True, output=output)


class ChannelSetupTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "channel_setup"
    description = "Configure and register a channel plugin"
    params = {
        "channel_name": ToolParam(str, "Channel name, e.g. 'telegram'"),
        "command": ToolParam(str, "Executable to run for this channel, e.g. 'hiro-channel-telegram'"),
        "enabled": ToolParam(bool, "Whether to enable the channel immediately", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
        "workspace_dir": ToolParam(
            str,
            "Working dir for `uv run`. Empty string runs the command as-is (e.g. an "
            "isolated `uv tool install` binary); omit to auto-detect the uv workspace.",
            required=False,
        ),
    }

    def execute(
        self,
        channel_name: str,
        command: str,
        enabled: bool = True,
        workspace: str | None = None,
        workspace_dir: str | None = None,
    ) -> ChannelSetupResult:
        workspace_path = _resolve_path(workspace)
        existing = load_channel_config(workspace_path, channel_name)

        # The devices channel is force-enabled only while the `devices` feature is
        # active; when the feature is hidden it is treated like any other channel.
        if channel_name == MANDATORY_CHANNEL_NAME and feature_active(MANDATORY_CHANNEL_NAME):
            enabled = True

        cmd_parts = command.split()
        # An explicit workspace_dir (including "") wins: a channel installed as an
        # isolated `uv tool` binary must run the command as-is, NOT be wrapped in
        # `uv run --directory <workspace>` (which would use the shared workspace env
        # and break plugins that need their own deps, e.g. WhatsApp's protobuf 7).
        if workspace_dir is not None:
            resolved_workspace_dir = workspace_dir
        else:
            uv_workspace = find_workspace_root()
            resolved_workspace_dir = str(uv_workspace) if uv_workspace else (
                existing.workspace_dir if existing else ""
            )

        channel_data = existing.config if existing else {}
        if channel_name == MANDATORY_CHANNEL_NAME:
            current = load_config(workspace_path)
            channel_data = {
                **channel_data,
                "gateway_url": current.gateway_url,
                "device_id": current.device_id,
                "master_key_path": str(master_key_path(workspace_path, current)),
                "ping_interval": channel_data.get("ping_interval", 30),
            }

        cfg = ChannelConfig(
            name=channel_name,
            enabled=enabled,
            command=cmd_parts,
            config=channel_data,
            workspace_dir=resolved_workspace_dir,
        )
        save_channel_config(workspace_path, cfg)

        return ChannelSetupResult(
            name=channel_name,
            enabled=enabled,
            command=command,
            workspace_dir=resolved_workspace_dir,
        )


class ChannelEnableTool(Tool):
    name = "channel_enable"
    description = "Enable a configured channel plugin"
    params = {
        "channel_name": ToolParam(str, "Channel name to enable"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, channel_name: str, workspace: str | None = None) -> ChannelEnableResult:
        workspace_path = _resolve_path(workspace)
        cfg = load_channel_config(workspace_path, channel_name)
        if cfg is None:
            raise ValueError(
                f"Channel '{channel_name}' is not configured. "
                f"Run channel_setup first."
            )
        cfg.enabled = True
        save_channel_config(workspace_path, cfg)
        return ChannelEnableResult(name=channel_name, enabled=True)


class ChannelDisableTool(Tool):
    name = "channel_disable"
    description = "Disable a channel plugin without removing its configuration"
    params = {
        "channel_name": ToolParam(str, "Channel name to disable"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, channel_name: str, workspace: str | None = None) -> ChannelDisableResult:
        workspace_path = _resolve_path(workspace)
        # Mandatory only while the `devices` feature is active (see features.py).
        if channel_name == MANDATORY_CHANNEL_NAME and feature_active(MANDATORY_CHANNEL_NAME):
            raise ValueError(f"The '{MANDATORY_CHANNEL_NAME}' channel is mandatory and cannot be disabled.")
        cfg = load_channel_config(workspace_path, channel_name)
        if cfg is None:
            raise ValueError(f"Channel '{channel_name}' is not configured.")
        cfg.enabled = False
        save_channel_config(workspace_path, cfg)
        return ChannelDisableResult(name=channel_name, enabled=False)


class ChannelConfigShowTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "channel_config_show"
    description = "Show a channel plugin's stored config values"
    params = {
        "channel_name": ToolParam(str, "Channel name, e.g. 'whatsapp'"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, channel_name: str, workspace: str | None = None) -> ChannelConfigResult:
        workspace_path = _resolve_path(workspace)
        cfg = load_channel_config(workspace_path, channel_name)
        if cfg is None:
            raise ValueError(f"Channel '{channel_name}' is not configured.")
        return ChannelConfigResult(name=channel_name, config=dict(cfg.config))


class ChannelConfigSetTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "channel_config_set"
    description = "Set (or, with no value, unset) a config key on a channel plugin"
    params = {
        "channel_name": ToolParam(str, "Channel name, e.g. 'whatsapp'"),
        "key": ToolParam(str, "Config key to set or unset"),
        "value": ToolParam(str, "JSON or string value; omit to unset the key", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        channel_name: str,
        key: str,
        value: str | None = None,
        workspace: str | None = None,
    ) -> ChannelConfigResult:
        workspace_path = _resolve_path(workspace)
        cfg = load_channel_config(workspace_path, channel_name)
        if cfg is None:
            raise ValueError(
                f"Channel '{channel_name}' is not configured. Run channel_setup first."
            )
        # Config changes reach a running plugin on the next channel.configure push
        # (i.e. after a restart); live re-push is a later phase (hot reload).
        descriptor = load_channel_descriptor(workspace_path, channel_name)
        schema = descriptor.config_schema if descriptor is not None else None
        secrets = secret_keys(schema) if schema else set()
        if key in secrets:
            # §5.6 — secret-declared keys go to the keyring; config keeps only a marker.
            _apply_secret_write(workspace_path, channel_name, key, value, cfg)
        else:
            if value is None:
                cfg.config.pop(key, None)
            else:
                cfg.config[key] = _parse_config_value(value)
            # §5.1 — validate against the schema the plugin declared at registration
            # (persisted as a descriptor). Coercion aligns loosely-typed CLI/HTTP values
            # with the declared types (e.g. a phone number typed as digits → string)
            # before validating; the coerced dict is what we persist. Secret keys hold a
            # marker, so they're excluded from value validation. A channel that never
            # registered has no descriptor, so writes pass through unvalidated.
            if schema:
                cfg.config = coerce_and_validate_config(
                    schema, cfg.config, secret_keys=secrets
                )
        save_channel_config(workspace_path, cfg)
        return ChannelConfigResult(name=channel_name, config=dict(cfg.config))


class ChannelRemoveTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "channel_remove"
    description = "Remove a channel plugin's configuration permanently"
    params = {
        "channel_name": ToolParam(str, "Channel name to remove"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, channel_name: str, workspace: str | None = None) -> ChannelRemoveResult:
        workspace_path = _resolve_path(workspace)
        # Mandatory only while the `devices` feature is active (see features.py).
        if channel_name == MANDATORY_CHANNEL_NAME and feature_active(MANDATORY_CHANNEL_NAME):
            raise ValueError(f"The '{MANDATORY_CHANNEL_NAME}' channel is mandatory and cannot be removed.")
        removed = delete_channel_config(workspace_path, channel_name)
        return ChannelRemoveResult(name=channel_name, removed=removed)
