from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.server_info import build_policy_snapshot
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


@dataclass
class PolicyGetResult:
    snapshot: dict[str, Any]


class PolicyGetTool(Tool):
    name = "policy_get"
    description = "Get workspace media policy snapshot (saved preferences only; channels use conversation_channel_list)"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        workspace: str | None = None,
        *,
        workspace_path: Path | None = None,
    ) -> PolicyGetResult:
        resolved_workspace_path = workspace_path or _resolve_path(workspace)
        snapshot = build_policy_snapshot(resolved_workspace_path)
        return PolicyGetResult(snapshot=snapshot.model_dump(mode="json"))
