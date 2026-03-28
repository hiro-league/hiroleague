"""HiroAdmin — route registration and NiceGUI bootstrap on admin_port.

Entry point: `run_admin_ui` (used by `hirocli.runtime.server_process` when `--admin`).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from hiro_commons.log import Logger

if TYPE_CHECKING:
    from hirocli.admin.context import AdminContext
    from hirocli.runtime.server_context import ServerContext

log = Logger.get("ADMIN")

_admin_routes_initialized = False


def build_admin_context(ctx: ServerContext) -> "AdminContext":
    """Build frozen context for the admin shell (workspace + log paths)."""
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
        log.warning("Failed to resolve gateway log dir for admin UI", error=str(exc))

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


def register_admin_routes() -> None:
    """Import page modules (side effects on admin_router), then mount router on core.app once."""
    global _admin_routes_initialized
    if _admin_routes_initialized:
        return
    _admin_routes_initialized = True

    from nicegui import core

    from hirocli.admin.router import admin_router
    from hirocli.admin.shell.layout import register_shell_shared_styles

    register_shell_shared_styles()

    from hirocli.admin.features.catalog import page as _catalog  # noqa: F401
    from hirocli.admin.features.channels import page as _channels  # noqa: F401
    from hirocli.admin.features.characters import page as _characters  # noqa: F401
    from hirocli.admin.features.dashboard import page as _dashboard  # noqa: F401
    from hirocli.admin.features.devices import page as _devices  # noqa: F401
    from hirocli.admin.features.gateways import page as _gateways  # noqa: F401
    from hirocli.admin.features.logs import page as _logs  # noqa: F401
    from hirocli.admin.features.metrics import page as _metrics  # noqa: F401
    from hirocli.admin.features.providers import page as _providers  # noqa: F401
    from hirocli.admin.features.workspaces import page as _workspaces  # noqa: F401
    from hirocli.admin.stubs import register_stub_pages

    register_stub_pages(admin_router)
    core.app.include_router(admin_router)
    log.info("Hiro Admin routes mounted", base_path="/")


async def run_admin_ui(ctx: ServerContext) -> None:
    """Start the NiceGUI admin UI and shut it down when stop_event fires."""
    from nicegui import ui

    from hirocli.admin.context import set_runtime_context
    from hirocli.admin.shared.theme import apply_theme

    set_runtime_context(build_admin_context(ctx))
    register_admin_routes()
    apply_theme()

    admin_app = FastAPI(title="Hiro Admin")
    ui.run_with(
        admin_app,
        title="Hiro Admin",
        show_welcome_message=False,
        storage_secret=f"hiro-admin-{ctx.config.device_id}",
    )

    uv_config = uvicorn.Config(
        app=admin_app,
        host="127.0.0.1",
        port=ctx.config.admin_port,
        log_level="warning",
        loop="none",
    )
    server = uvicorn.Server(uv_config)

    serve_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(ctx.stop_event.wait())

    log.info(
        f"🎉 Hiro Dashboard Ready - http://127.0.0.1:{ctx.config.admin_port}",
        admin_url=f"http://127.0.0.1:{ctx.config.admin_port}/",
    )

    done, pending = await asyncio.wait(
        [serve_task, stop_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if stop_task in done:
        server.should_exit = True
        await serve_task

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    log.info("Admin UI stopped")
