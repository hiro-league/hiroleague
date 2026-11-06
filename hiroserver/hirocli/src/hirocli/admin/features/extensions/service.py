"""Extension pairing, the paired list, removal and the listen address for the admin API.

A facade over the extension tools (tools/extension.py). Live state — who is
connected, the test call, closing a removed extension's connection — comes from
the running server's ExtensionManager and is added by the route.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hirocli.admin.shared.result import Result
from hirocli.domain.workspace import resolve_workspace
from hirocli.tools.extension import (
    ExtensionAddResult,
    ExtensionAddressResult,
    ExtensionAddressTool,
    ExtensionAddTool,
    ExtensionListTool,
    ExtensionRemoveTool,
)


class ExtensionService:
    """Facade over extension tools."""

    def workspace_path(self, workspace_id: str | None) -> Path | None:
        if not workspace_id:
            return None
        try:
            entry, _ = resolve_workspace(workspace_id)
        except Exception:
            return None
        return Path(entry.path)

    def list_extensions(self, workspace_id: str | None) -> Result[list[dict[str, Any]]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            result = ExtensionListTool().execute(workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(list(result.extensions))

    def generate_pairing_code(self, workspace_id: str | None) -> Result[ExtensionAddResult]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            return Result.success(ExtensionAddTool().execute(workspace=workspace_id))
        except Exception as exc:
            return Result.failure(str(exc))

    def remove_extension(self, extension_id: str, workspace_id: str | None) -> Result[str]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        if not extension_id:
            return Result.failure("Extension ID is required.")
        try:
            result = ExtensionRemoveTool().execute(extension_id=extension_id, workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        if not result.removed:
            return Result.failure(f"Extension '{extension_id}' was not found or already removed.")
        return Result.success("Extension removed.")

    def address(self, workspace_id: str | None, host: str | None = None) -> Result[ExtensionAddressResult]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            return Result.success(ExtensionAddressTool().execute(host=host, workspace=workspace_id))
        except Exception as exc:
            return Result.failure(str(exc))
