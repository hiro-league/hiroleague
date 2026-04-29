"""Auto-start registration wrappers for Hiro workspaces.

Uses the workspace *id* (UUID) as the stable identifier for task names and
CLI ``--workspace`` arguments so that workspace renames don't break autostart.
"""

from __future__ import annotations

from hiro_commons.autostart import (
    AutostartMethod,
    register_autostart as commons_register_autostart,
    register_autostart_elevated as commons_register_autostart_elevated,
    unregister_autostart as commons_unregister_autostart,
    unregister_autostart_elevated as commons_unregister_autostart_elevated,
)


def register_autostart(workspace_id: str) -> AutostartMethod:
    """Register Hiro to start automatically on user login for the given workspace."""
    return commons_register_autostart(
        workspace_id,
        entry_name_prefix="hiro",
        executable_name="hiro",
        launch_args=["start", "--workspace", workspace_id],
    )


def register_autostart_elevated(workspace_id: str) -> bool:
    """Windows only: register a /RL HIGHEST task via UAC prompt."""
    return commons_register_autostart_elevated(
        workspace_id,
        entry_name_prefix="hiro",
        executable_name="hiro",
        launch_args=["start", "--workspace", workspace_id],
    )


def unregister_autostart(workspace_id: str) -> None:
    """Remove auto-start registrations for the given workspace."""
    commons_unregister_autostart(workspace_id, entry_name_prefix="hiro")


def unregister_autostart_elevated(workspace_id: str) -> bool:
    """Windows only: delete the Task Scheduler task via UAC prompt."""
    return commons_unregister_autostart_elevated(workspace_id, entry_name_prefix="hiro")
