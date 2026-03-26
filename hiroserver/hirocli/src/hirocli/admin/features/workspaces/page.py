"""Workspaces — thin page; controller owns UI (guidelines §1.2, §2.3)."""

from __future__ import annotations

from hirocli.admin.context import get_runtime_context
from hirocli.admin.features.workspaces.controller import WorkspacesPageController
from hirocli.admin.router import v2_router
from hirocli.admin.shell.layout import create_page_layout


@v2_router.page("/workspaces")
async def workspaces_page() -> None:
    ctx = get_runtime_context()
    hosting_id = ctx.hosting_workspace_id if ctx else None
    create_page_layout(active_path="/v2/workspaces")
    await WorkspacesPageController(hosting_id).mount()
