from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.server_info import build_server_info_snapshot
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


@dataclass
class ServerInfoGetResult:
    snapshot: dict[str, Any]


class ServerInfoGetTool(Tool):
    name = "server_info_get"
    description = "Get the current server.info snapshot with policy and channel capabilities"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
    ) -> ServerInfoGetResult:
        resolved_workspace_path = workspace_path or _resolve_path(workspace)
        snapshot = build_server_info_snapshot(resolved_workspace_path)
        return ServerInfoGetResult(snapshot=snapshot.model_dump(mode="json"))
