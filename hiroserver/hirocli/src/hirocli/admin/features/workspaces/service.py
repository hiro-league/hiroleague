"""Workspace operations — wraps workspace + server tools; no NiceGUI (guidelines §1.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hiro_commons.process import is_running, read_pid

from hirocli.constants import PID_FILENAME
from hirocli.domain.workspace import WorkspaceError
from hirocli.tools.server import RestartTool, SetupTool, StartTool, StopTool
from hirocli.tools.workspace import (
    WorkspaceCreateTool,
    WorkspaceGetPublicKeyTool,
    WorkspaceListTool,
    WorkspaceRegenerateKeyTool,
    WorkspaceRemoveTool,
    WorkspaceUpdateTool,
)

from hirocli.admin.shared.result import Result
from hirocli.admin.shared.stderr_log import stderr_log_info

_MSG_STOP_HOSTING = (
    "Cannot stop the workspace running this Admin UI. "
    "Start another workspace's Admin UI to do this."
)
_MSG_REMOVE_HOSTING = (
    "Cannot remove the workspace running this Admin UI. "
    "Start another workspace's Admin UI to do this."
)


def _is_hosting(ws_id: str, hosting_workspace_id: str | None) -> bool:
    return bool(hosting_workspace_id and ws_id == hosting_workspace_id)


class WorkspaceService:
    """Facade over tools with explicit hosting-workspace safety checks."""

    def list_rows(self, hosting_workspace_id: str | None) -> Result[list[dict[str, Any]]]:
        try:
            ws_result = WorkspaceListTool().execute()
        except Exception as exc:
            return Result.failure(str(exc))
        rows: list[dict[str, Any]] = []
        for ws in ws_result.workspaces:
            ws_path = Path(ws["path"])
            try:
                pid = read_pid(ws_path, PID_FILENAME)
                running = is_running(pid)
            except Exception:
                pid = None
                running = False
            rows.append(
                {
                    **ws,
                    "running": running,
                    "pid": pid,
                    "is_current": ws["id"] == hosting_workspace_id,
                    **stderr_log_info(ws_path),
                }
            )
        return Result.success(rows)

    def create(self, name: str, path: str | None) -> Result[str]:
        if not name.strip():
            return Result.failure("Name is required.")
        try:
            WorkspaceCreateTool().execute(name=name.strip(), path=path)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(f"Workspace '{name.strip()}' created.")

    def remove(self, workspace_id: str, purge: bool, hosting_workspace_id: str | None) -> Result[str]:
        if _is_hosting(workspace_id, hosting_workspace_id):
            return Result.failure(_MSG_REMOVE_HOSTING)
        try:
            r = WorkspaceRemoveTool().execute(workspace=workspace_id, purge=purge)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(f"Workspace '{r.name}' removed.")

    def update(
        self,
        workspace_id: str,
        *,
        name: str | None,
        gateway_url: str | None,
        set_default: bool,
        previous_display_name: str,
    ) -> Result[str]:
        if name is None and gateway_url is None and not set_default:
            return Result.failure("Nothing to update.")
        try:
            result = WorkspaceUpdateTool().execute(
                workspace=workspace_id,
                name=name,
                set_default=set_default,
                gateway_url=gateway_url,
            )
        except (WorkspaceError, ValueError) as exc:
            return Result.failure(str(exc))
        except Exception as exc:
            return Result.failure(str(exc))
        msgs: list[str] = []
        if result.renamed:
            msgs.append(f"renamed to '{result.name}'")
        if result.default_changed:
            msgs.append("set as default")
        if result.gateway_updated:
            msgs.append("gateway updated")
        label = previous_display_name
        return Result.success(
            f"Workspace '{label}' updated: {', '.join(msgs) or 'no changes'}."
        )

    def start(self, workspace_id: str) -> Result[tuple[str, bool, int | None]]:
        """Returns (workspace_name, already_running, pid)."""
        try:
            result = StartTool().execute(workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success((result.workspace, result.already_running, result.pid))

    def stop(self, workspace_id: str, hosting_workspace_id: str | None) -> Result[str]:
        if _is_hosting(workspace_id, hosting_workspace_id):
            return Result.failure(_MSG_STOP_HOSTING)
        try:
            result = StopTool().execute(workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(f"'{result.workspace}' stopped.")

    def restart(self, workspace_id: str, *, admin: bool) -> Result[None]:
        try:
            RestartTool().execute(workspace=workspace_id, admin=admin)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(None)

    def setup(
        self,
        workspace_id: str,
        *,
        gateway_url: str,
        http_port: int | None,
        skip_autostart: bool,
        start_server: bool,
        elevated_task: bool,
    ) -> Result[Any]:
        if not gateway_url.strip():
            return Result.failure("Gateway WebSocket URL is required.")
        try:
            return Result.success(
                SetupTool().execute(
                    gateway_url=gateway_url.strip(),
                    workspace=workspace_id,
                    http_port=http_port,
                    skip_autostart=skip_autostart,
                    start_server=start_server,
                    elevated_task=elevated_task,
                )
            )
        except Exception as exc:
            return Result.failure(str(exc))

    def get_public_key(self, workspace_id: str) -> Result[str]:
        try:
            r = WorkspaceGetPublicKeyTool().execute(workspace=workspace_id)
        except (WorkspaceError, ValueError) as exc:
            return Result.failure(str(exc))
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(r.public_key_b64)

    def regenerate_key(self, workspace_id: str) -> Result[str]:
        try:
            r = WorkspaceRegenerateKeyTool().execute(workspace=workspace_id)
        except (WorkspaceError, ValueError) as exc:
            return Result.failure(str(exc))
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(r.public_key_b64)

    def open_folder(self, folder_path: str) -> Result[None]:
        import platform
        import subprocess

        if not folder_path:
            return Result.failure("Folder path not available.")
        try:
            system = platform.system()
            if system == "Windows":
                subprocess.Popen(f'explorer "{folder_path}"')  # noqa: S603
            elif system == "Darwin":
                subprocess.Popen(["open", folder_path])  # noqa: S603
            else:
                subprocess.Popen(["xdg-open", folder_path])  # noqa: S603
        except Exception as exc:
            return Result.failure(f"Could not open folder: {exc}")
        return Result.success(None)
