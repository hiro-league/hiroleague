"""HiroAdmin v2 — register routes on the shared NiceGUI app under /v2/.

Called from legacy `hirocli.ui.run.run_admin_ui` after legacy `register_pages()` so both
UIs are served on the same admin_port (legacy at `/`, v2 at `/v2/...`).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hiro_commons.log import Logger

if TYPE_CHECKING:
    from hirocli.admin.context import AdminContext
    from hirocli.runtime.server_context import ServerContext

log = Logger.get("ADMIN")

_v2_admin_initialized = False


def build_admin_context(ctx: ServerContext) -> "AdminContext":
    """Build frozen context for v2 shell (same resolution as legacy ui/state)."""
    from hirocli.admin.context import AdminContext

    gateway_log_dir: Path | None = None
    try:
        from hirogateway.instance import load_registry as _load_gw_registry
        from hirogateway.config import load_config as _load_gw_config, resolve_log_dir as _gw_resolve_log_dir

        _gw_registry = _load_gw_registry()
        if _gw_registry.instances:
            _gw_name = _gw_registry.default_instance or next(iter(_gw_registry.instances))
            _gw_entry = _gw_registry.instances.get(_gw_name)
            if _gw_entry is not None:
                _gw_instance_path = Path(_gw_entry.path)
                _gw_config = _load_gw_config(_gw_instance_path)
                gateway_log_dir = _gw_resolve_log_dir(_gw_instance_path, _gw_config)
    except Exception as exc:
        log.warning("Failed to resolve gateway log dir for admin v2 UI", error=str(exc))

    workspace_id: str | None = None
    workspace_name: str | None = None
    try:
        from hirocli.domain.workspace import load_registry

        registry = load_registry()
        for ws_id, entry in registry.workspaces.items():
            if Path(entry.path).resolve() == ctx.workspace_path.resolve():
                workspace_id = ws_id
                workspace_name = entry.name
                break
    except Exception:
        pass

    return AdminContext(
        hosting_workspace_id=workspace_id,
        hosting_workspace_name=workspace_name,
        workspace_path=ctx.workspace_path,
        log_dir=ctx.log_dir,
        gateway_log_dir=gateway_log_dir,
    )


def register_v2_routes() -> None:
    """Import v2 page modules (side effects on v2_router), then mount router on core.app once."""
    global _v2_admin_initialized
    if _v2_admin_initialized:
        return
    _v2_admin_initialized = True

    from nicegui import core

    from hirocli.admin.router import v2_router
    from hirocli.admin.shell.layout import register_shell_shared_styles

    register_shell_shared_styles()

    # Decorators register on v2_router when modules load.
    from hirocli.admin.features.dashboard import page as _dashboard  # noqa: F401
    from hirocli.admin.features.workspaces import page as _workspaces  # noqa: F401
    from hirocli.admin.stubs import register_stub_pages

    register_stub_pages(v2_router)
    core.app.include_router(v2_router)
    log.info("Hiro Admin v2 routes mounted", base_path="/v2/")
