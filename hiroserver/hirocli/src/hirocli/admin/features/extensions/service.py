"""Extension pairing, the one list of every extension, removal and the listen address for the admin API.

A facade over the extension tools (tools/extension.py). Live state — who is
connected, the test call, closing a removed extension's connection — comes from
the running server's ExtensionManager and is added by the route.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hirocli.admin.shared.result import Result
from hirocli.domain.extensions import PairedExtension, list_paired_extensions
from hirocli.domain.workspace import resolve_workspace
from hirocli.tools.extension import (
    ExtensionAddResult,
    ExtensionAddressResult,
    ExtensionAddressTool,
    ExtensionAddTool,
    ExtensionListTool,
    ExtensionPairAgainTool,
    ExtensionRemoveResult,
    ExtensionRemoveTool,
)
from hiro_commons.log import Logger

log = Logger.get("ADMIN.EXTENSIONS")


class ExtensionService:
    """Facade over extension tools."""

    def workspace_path(self, workspace_id: str | None) -> Path | None:
        if not workspace_id:
            return None
        try:
            entry, _ = resolve_workspace(workspace_id)
        except Exception as exc:
            log.debug("Workspace not found — no extensions folder for it", workspace_id=workspace_id, error=str(exc))
            return None
        return Path(entry.path)

    def list_extensions(self, workspace_id: str | None) -> Result[list[dict[str, Any]]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            result = ExtensionListTool().execute(workspace=workspace_id)
        except Exception:
            log.warning("⚠️ Extensions list failed — HiroAdmin · extensions", workspace_id=workspace_id, exc_info=True)
            return Result.failure("The list of extensions couldn't be read; the server's log says why.")
        return Result.success(list(result.extensions))

    def generate_pairing_code(self, workspace_id: str | None) -> Result[ExtensionAddResult]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            return Result.success(ExtensionAddTool().execute(workspace=workspace_id))
        except Exception as exc:
            log.warning("⚠️ Extension pairing code failed — HiroAdmin · extensions", workspace_id=workspace_id, error=str(exc), exc_info=True)
            return Result.failure(str(exc))

    def pair_again_code(self, extension_id: str, workspace_id: str | None) -> Result[ExtensionAddResult]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            return Result.success(ExtensionPairAgainTool().execute(extension_id=extension_id, workspace=workspace_id))
        except ValueError as exc:
            # The tool's refusal is written for a person (gone, or a channel).
            return Result.failure(str(exc))

    def find(self, extension_id: str, workspace_id: str | None) -> PairedExtension | None:
        """One extension of the list, of any kind, or None."""
        workspace_path = self.workspace_path(workspace_id)
        if workspace_path is None:
            return None
        return next(
            (e for e in list_paired_extensions(workspace_path, kind=None) if e.extension_id == extension_id), None
        )

    def remove_extension(self, extension_id: str, workspace_id: str | None) -> Result[ExtensionRemoveResult]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        if not extension_id:
            return Result.failure("Extension ID is required.")
        try:
            result = ExtensionRemoveTool().execute(extension_id=extension_id, workspace=workspace_id)
        except ValueError as exc:
            # The tool's refusal is written for a person (the mandatory channel).
            return Result.failure(str(exc))
        except Exception:
            log.warning(
                "⚠️ Extension remove failed — HiroAdmin · extensions",
                extension_id=extension_id,
                workspace_id=workspace_id,
                exc_info=True,
            )
            return Result.failure("The extension couldn't be removed; the server's log says why.")
        if not result.removed:
            return Result.failure("That extension isn't in the list any more.")
        return Result.success(result)

    def address(self, workspace_id: str | None, host: str | None = None) -> Result[ExtensionAddressResult]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            return Result.success(ExtensionAddressTool().execute(host=host, workspace=workspace_id))
        except Exception as exc:
            log.warning("⚠️ Extension address failed — HiroAdmin · extensions", workspace_id=workspace_id, host=host, error=str(exc), exc_info=True)
            return Result.failure(str(exc))
