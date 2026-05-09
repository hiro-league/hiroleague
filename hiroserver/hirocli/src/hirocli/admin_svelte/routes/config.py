"""Static admin config snapshot (non-streaming)."""

from __future__ import annotations

import dataclasses
import platform
from typing import Any

from fastapi import APIRouter

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.workspace_ctx import _hiro_package_version, _workspace_name
from hirocli.environment import get_environment_config

config_router = APIRouter()


@config_router.get("/config")
async def get_admin_config(workspace_id: SelectedWorkspaceIdDep) -> dict[str, Any]:
    config = get_environment_config()
    data = dataclasses.asdict(config)
    data.update(
        {
            "workspace_id": workspace_id,
            "workspace_name": _workspace_name(workspace_id),
            "python_version": platform.python_version(),
            "hiro_package_version": _hiro_package_version(),
        }
    )
    return {
        "ok": True,
        "error": None,
        "data": data,
    }
