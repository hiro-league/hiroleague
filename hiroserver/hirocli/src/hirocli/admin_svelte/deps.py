"""FastAPI dependencies for the Svelte admin API."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from hirocli.admin_svelte.workspace_ctx import _selected_workspace_id

# Canonical header name for OpenAPI; HTTP is case-insensitive (admin SPA sends ``x-hiro-workspace``).
HIRO_WORKSPACE_HEADER = "X-Hiro-Workspace"


def _resolved_workspace_id(
    x_hiro_workspace: str | None = Header(default=None, alias=HIRO_WORKSPACE_HEADER),
) -> str | None:
    """Resolved workspace id: header value if set, else hosting workspace."""
    return _selected_workspace_id(x_hiro_workspace)


SelectedWorkspaceIdDep = Annotated[str | None, Depends(_resolved_workspace_id)]
