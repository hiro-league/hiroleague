"""Extension tools — pairing codes, the paired list, removal, and the listen address.

Extensions are programs that run on their own (HomeHiro first) and sign in on the
workspace's extension socket (runtime/extension_manager.py). The CLI
(commands/extension.py) and the admin (admin/features/extensions) call these.
Live state (who is connected, the test call) comes from the running server's
ExtensionManager, read by the admin route directly.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.constants.network import DEFAULT_LOCALHOST

from ..domain.config import Config, load_config, save_config
from ..domain.extensions import list_paired_extensions, remove_paired_extension, start_extension_pairing
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam

# Addresses that mean "every interface": an extension can't dial these, so the
# address shown to type in uses this machine's name instead.
_ANY_ADDRESSES = frozenset({"0.0.0.0", "::", ""})


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


def extension_address(config: Config) -> str:
    """The ws:// address an extension types in to reach this workspace."""
    host = config.extension_host.strip()
    if host in _ANY_ADDRESSES:
        host = socket.gethostname()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6 literal
    return f"ws://{host}:{config.effective_extension_port()}"


def _iso(value: Any) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ExtensionAddResult:
    code: str
    expires_at: str
    address: str


@dataclass
class ExtensionListResult:
    extensions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExtensionRemoveResult:
    removed: bool
    extension_id: str


@dataclass
class ExtensionAddressResult:
    host: str
    port: int
    address: str
    changed: bool
    restart_required: bool
    note: str = ""


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class ExtensionAddTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_add"
    description = "Generate a short-lived pairing code to connect an extension (such as HomeHiro) to this workspace"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
        "ttl_seconds": ToolParam(int, "Pairing code lifetime in seconds", required=False),
    }

    def execute(self, workspace: str | None = None, ttl_seconds: int | None = None) -> ExtensionAddResult:
        workspace_path = _resolve_path(workspace)
        config = load_config(workspace_path)
        session = start_extension_pairing(
            workspace_path,
            code_length=config.pairing_code_length,
            ttl_seconds=ttl_seconds or config.pairing_code_ttl_seconds,
        )
        return ExtensionAddResult(
            code=session.code,
            expires_at=session.expires_at.isoformat().replace("+00:00", "Z"),
            address=extension_address(config),
        )


class ExtensionListTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_list"
    description = "List the extensions paired with this workspace"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> ExtensionListResult:
        workspace_path = _resolve_path(workspace)
        return ExtensionListResult(
            extensions=[
                {
                    "extension_id": ext.extension_id,
                    "name": ext.name,
                    "version": str(ext.info.get("version") or ""),
                    "description": str(ext.info.get("description") or ""),
                    "paired_at": _iso(ext.paired_at),
                    "last_seen": _iso(ext.last_seen),
                }
                for ext in list_paired_extensions(workspace_path)
            ]
        )


class ExtensionRemoveTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_remove"
    description = "Remove a paired extension; it is refused until paired again"
    params = {
        "extension_id": ToolParam(str, "Extension ID to remove"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, extension_id: str, workspace: str | None = None) -> ExtensionRemoveResult:
        workspace_path = _resolve_path(workspace)
        removed = remove_paired_extension(workspace_path, extension_id)
        return ExtensionRemoveResult(removed=removed, extension_id=extension_id)


class ExtensionAddressTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_address"
    description = (
        "Show or set the address extensions connect on (127.0.0.1 = this machine only; "
        "the Docker bridge or LAN address reaches extensions elsewhere). Needs a restart."
    )
    params = {
        "host": ToolParam(str, "Address to listen on; omit to only show it", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, host: str | None = None, workspace: str | None = None) -> ExtensionAddressResult:
        workspace_path = _resolve_path(workspace)
        config = load_config(workspace_path)
        changed = False
        if host is not None:
            new_host = host.strip() or DEFAULT_LOCALHOST
            if new_host != config.extension_host:
                config.extension_host = new_host
                save_config(workspace_path, config)
                changed = True
        local = config.extension_host in {DEFAULT_LOCALHOST, "localhost", "::1"}
        return ExtensionAddressResult(
            host=config.extension_host,
            port=config.effective_extension_port(),
            address=extension_address(config),
            changed=changed,
            restart_required=changed,
            note=(
                ""
                if local
                else "Not encrypted: fine on the Docker bridge; on a LAN, anyone on the network "
                "can read the messages (sign-in still holds)."
            ),
        )
