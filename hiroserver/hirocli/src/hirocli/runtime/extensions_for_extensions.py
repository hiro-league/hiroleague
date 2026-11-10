"""Every paired extension and its repo, for extensions (``extensions.list``).

The code reports keep a report for the core and for each extension, each from its own repo (hiro-code-reports'
R4). An extension names its repo in what it says about itself (``ExtensionInfo.repo``); the core keeps that with
the paired extension (the ``extensions`` table's ``info``) and answers it here, live while the extension is
connected, else as it last said. Contract: hiro_channel_sdk.constants.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from hiro_channel_sdk.constants import METHOD_EXTENSIONS_LIST

from ..domain.extensions import list_paired_extensions
from .request_handler import EXTENSIONS_ONLY, RequestContext


def _entry(extension_id: str, name: str, info: dict[str, Any], connected: bool) -> dict[str, Any]:
    return {
        "extension_id": extension_id,
        "name": str(info.get("name") or name or extension_id),
        "version": str(info.get("version") or ""),
        "description": str(info.get("description") or ""),
        "repo": str(info.get("repo") or ""),
        "connected": connected,
    }


async def handle_extensions_list(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Every paired extension, in the order it was paired: its name, repo, and whether it is connected now."""
    del params
    manager = ctx.server_ctx.extension_manager
    live = manager.snapshot() if manager is not None else {}
    paired = await asyncio.to_thread(list_paired_extensions, Path(ctx.server_ctx.workspace_path))
    extensions = []
    for ext in paired:
        conn = live.get(ext.extension_id)
        info = (conn.get("info") or {}) if conn else (ext.info or {})
        extensions.append(_entry(ext.extension_id, ext.name, info, connected=conn is not None))
    return {"extensions": extensions}


EXTENSIONS_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_EXTENSIONS_LIST, handle_extensions_list, EXTENSIONS_ONLY),
)
