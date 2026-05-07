"""File communication tools — ``files.head`` (blob discovery)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.blob_store import DEFAULT_CHUNK_SIZE, chunk_count_for_size
from ..domain.files_resolver import resolve_ref
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam


def _workspace_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


@dataclass
class FilesHeadResult:
    blob_id: str
    size: int
    media_type: str
    chunk_size: int
    chunk_count: int


class FilesHeadTool(Tool):
    name = "files_head"
    description = "Resolve a file ref to blob metadata (size, sha256 id, chunk layout)"
    params = {
        "ref": ToolParam(str, "Reference such as character_photo:hiro"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, ref: str, workspace: str | None = None) -> FilesHeadResult:
        wp = _workspace_path(workspace)
        path, media_type, blob_id = resolve_ref(wp, ref)
        size = path.stat().st_size
        chunk_size = DEFAULT_CHUNK_SIZE
        chunk_count = chunk_count_for_size(size, chunk_size)
        return FilesHeadResult(
            blob_id=blob_id,
            size=size,
            media_type=media_type,
            chunk_size=chunk_size,
            chunk_count=chunk_count,
        )
