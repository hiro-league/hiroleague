"""Hiro Admin FastAPI bootstrap on admin_port."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from hiro_commons.log import Logger
from hirocli.runtime.asgi import ShutdownCancellationGuard

if TYPE_CHECKING:
    from hirocli.admin.context import AdminContext
    from hirocli.runtime.server_context import ServerContext

log = Logger.get("ADMIN")


def build_admin_context(ctx: ServerContext) -> "AdminContext":
    """Build frozen context for the admin shell."""
    from hirocli.admin.context import AdminContext

    gateway_log_dir: Path | None = None
    try:
        from hirogateway.config import (
            load_config as _load_gw_config,
            resolve_log_dir as _gw_resolve_log_dir,
        )
        from hirogateway.instance import load_registry as _load_gw_registry

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


async def run_admin_ui(ctx: ServerContext) -> None:
    """Start the Svelte admin UI and shut it down when stop_event fires."""
    from hirocli.admin.context import set_runtime_context
    from hirocli.admin_svelte.api import include_admin_svelte_api
    from hirocli.admin_svelte.static_server import mount_admin_svelte_static

    set_runtime_context(build_admin_context(ctx))

    admin_app = FastAPI(title="Hiro Admin")
    include_admin_svelte_api(admin_app)
    mount_admin_svelte_static(admin_app)

    uv_config = uvicorn.Config(
        app=ShutdownCancellationGuard(admin_app, ctx.stop_event),
        host="127.0.0.1",
        port=ctx.config.admin_port,
        log_level="warning",
        loop="none",
    )
    server = uvicorn.Server(uv_config)

    serve_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(ctx.stop_event.wait())

    log.info(
        "Hiro Admin ready",
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


async def run_admin_ui_logged(ctx: ServerContext) -> None:
    """Run admin UI; log failures hidden by gather(return_exceptions=True)."""
    try:
        await run_admin_ui(ctx)
    except Exception as exc:
        log.error(
            f"Admin UI failed - {type(exc).__name__}: {exc}",
            exc_info=True,
        )
