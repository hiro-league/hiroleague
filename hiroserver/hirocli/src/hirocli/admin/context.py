"""Runtime context for HiroAdmin v2 — replaces module globals from legacy ui/state.py."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Set once at startup in admin.run before pages are served.
_runtime: AdminContext | None = None


@dataclass(frozen=True)
class AdminContext:
    """Immutable process context for the admin UI hosting workspace and log paths."""

    hosting_workspace_id: str | None
    hosting_workspace_name: str | None
    workspace_path: Path | None
    log_dir: Path | None
    gateway_log_dir: Path | None


def set_runtime_context(ctx: AdminContext) -> None:
    """Called from `hirocli.ui.run.run_admin_ui` before v2 routes are registered."""
    global _runtime
    _runtime = ctx


def get_runtime_context() -> AdminContext | None:
    """Return the context set at startup, or None if not initialized."""
    return _runtime


def get_selected_workspace() -> str | None:
    """Current header workspace id from per-browser storage (valid during a page request)."""
    from nicegui import app as nicegui_app

    return nicegui_app.storage.user.get("selected_workspace")


def ensure_selected_workspace_storage(valid_ids: list[str], default_id: str | None) -> str | None:
    """Read selected_workspace from user storage, coerce to a valid id, write back, return it.

    Keeps workspace selection logic out of layout.py (guidelines §1.2 / §2.2).
    """
    from nicegui import app as nicegui_app

    stored = nicegui_app.storage.user.get("selected_workspace")
    selected_id = stored if stored in valid_ids else default_id
    nicegui_app.storage.user["selected_workspace"] = selected_id
    return selected_id
