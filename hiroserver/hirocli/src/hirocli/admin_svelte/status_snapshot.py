"""Aggregated workspace + gateway rows for admin status UI and SSE payloads."""

from __future__ import annotations

from typing import Any

from hirocli.admin.features.gateways.service import GatewayService
from hirocli.admin.features.workspaces.service import WorkspaceService
from hirocli.admin_svelte.workspace_ctx import _hosting_workspace_id


def _workspace_status_label(row: dict[str, Any] | None) -> tuple[str, str]:
    if row is None or not row.get("running"):
        return "stopped", "Workspace not running"
    if not row.get("ws_connected"):
        return "running_disconnected", "Workspace running, gateway disconnected"
    return "connected", "Workspace running and connected to gateway"


def _status_snapshot(workspace_id: str | None = None) -> dict[str, Any]:
    hosting_workspace_id = _hosting_workspace_id()
    workspaces = WorkspaceService().list_rows(hosting_workspace_id)
    gateways = GatewayService().list_instances()
    workspace_rows = workspaces.data if workspaces.ok and workspaces.data is not None else []
    gateway_rows = gateways.data if gateways.ok and gateways.data is not None else []

    selected_workspace_id = workspace_id or hosting_workspace_id
    selected_row = next(
        (row for row in workspace_rows if selected_workspace_id and row.get("id") == selected_workspace_id),
        None,
    )
    if selected_row is None:
        selected_row = next((row for row in workspace_rows if row.get("is_current")), None)
    if selected_row is None and workspace_rows:
        selected_row = workspace_rows[0]

    status, status_label = _workspace_status_label(selected_row)
    return {
        "workspace": selected_row,
        "workspace_status": status,
        "workspace_status_label": status_label,
        "workspaces": workspace_rows,
        "workspaces_error": None if workspaces.ok else workspaces.error,
        "gateways": gateway_rows,
        "gateways_error": None if gateways.ok else gateways.error,
        "hosting_workspace_id": hosting_workspace_id,
    }
