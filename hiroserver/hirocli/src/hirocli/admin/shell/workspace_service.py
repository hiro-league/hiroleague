"""Shell-only service: workspace list for the header selector (no NiceGUI imports)."""

from __future__ import annotations

from hiro_commons.log import Logger

from hirocli.tools.workspace import WorkspaceListTool

log = Logger.get("ADMIN.SHELL")


class WorkspaceSelectService:
    """Loads workspace id/label map for the shell dropdown — wraps WorkspaceListTool."""

    @staticmethod
    def load_select_options(hosting_workspace_id: str | None) -> tuple[dict[str, str], str | None]:
        """Return ({workspace_id: display_label}, default_workspace_id). Empty dict on failure."""
        workspace_options: dict[str, str] = {}
        default_ws_id: str | None = None
        try:
            ws_result = WorkspaceListTool().execute()
            for ws in ws_result.workspaces:
                label = ws["name"]
                if hosting_workspace_id and ws["id"] == hosting_workspace_id:
                    label += " (this UI)"
                workspace_options[ws["id"]] = label
            default_ws_id = ws_result.default_workspace or next(iter(workspace_options), None)
        except Exception as exc:
            log.warning(
                "⚠️ Shell workspace selector — HiroServer · WorkspaceListTool failed",
                error=str(exc),
                exc_info=True,
            )
        return workspace_options, default_ws_id
