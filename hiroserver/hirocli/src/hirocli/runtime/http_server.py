"""FastAPI HTTP server for Hiro.

Runs concurrently with the WS client inside the same asyncio event loop.
Endpoints:
  GET  /status             — server and WS connection status
  GET  /channels           — connected channel plugin names and info
  GET  /tools              — list all registered tools and their schemas
  POST /invoke             — execute a tool by name with a flat params dict
  GET  /metrics            — latest metrics snapshot (if enabled)
  GET  /metrics/history    — historical snapshots for the last N minutes
  GET  /metrics/status     — collector config and state
  POST /metrics/configure  — runtime toggle and tuning
  POST /_shutdown          — trigger graceful server shutdown
  POST /_restart           — trigger graceful restart (shutdown + respawn)
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from hiro_commons.log import Logger
from hiro_commons.process import is_running, read_pid
from pydantic import BaseModel

from ..domain.config import load_state
from ..constants import APP_NAME, PID_FILENAME
from ..tools.registry import ToolExecutionError, ToolNotFoundError

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("HTTP")

app = FastAPI(title=APP_NAME, version="0.1.0", docs_url=None, redoc_url=None)

# Defaults — overwritten by server_process.py before the server starts.
# ctx holds the ServerContext; tool_registry, channel_info_provider, and
# metrics_collector are runtime services wired separately.
app.state.ctx = None
app.state.tool_registry = None
app.state.channel_info_provider = None
app.state.metrics_collector = None


def _ctx(request: Request) -> ServerContext:
    """Retrieve the ServerContext from app state (convenience for endpoints)."""
    ctx = request.app.state.ctx
    assert ctx is not None, "ServerContext not initialised"
    return ctx


def request_shutdown() -> None:
    """Trigger graceful shutdown with a short delay so HTTP responses can flush."""
    ctx = app.state.ctx
    if ctx is not None:
        asyncio.get_running_loop().call_later(0.5, ctx.stop_event.set)


def request_restart(admin: bool = False) -> None:
    """Trigger restart: graceful shutdown + respawn on exit."""
    ctx = app.state.ctx
    if ctx is not None:
        ctx.restart_requested = True
        ctx.restart_admin = admin
    request_shutdown()


@app.get("/status")
async def get_status(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    state = load_state(ctx.workspace_path)
    pid = read_pid(ctx.workspace_path, PID_FILENAME)
    return JSONResponse(
        {
            "running": is_running(pid),
            "pid": pid,
            "ws_connected": state.ws_connected,
            "last_connected": state.last_connected,
            "gateway_url": state.gateway_url,
        }
    )


@app.get("/channels")
async def get_channels(request: Request) -> JSONResponse:
    provider = request.app.state.channel_info_provider
    channels = provider() if provider else []
    return JSONResponse({"channels": channels})


@app.get("/tools")
async def get_tools(request: Request) -> JSONResponse:
    """Return the schema of every registered tool."""
    registry = request.app.state.tool_registry
    if registry is None:
        return JSONResponse({"tools": []})
    return JSONResponse({"tools": registry.schema()})


class InvokeRequest(BaseModel):
    tool: str
    params: dict[str, Any] = {}


@app.post("/invoke")
async def invoke_tool(body: InvokeRequest, request: Request) -> JSONResponse:
    """Execute a tool by name.

    Request body::

        { "tool": "device_add", "params": { "ttl_seconds": 120 } }

    Response on success::

        { "tool": "device_add", "result": { ... } }

    The result is the tool's return dataclass serialised to a dict.
    """
    registry = request.app.state.tool_registry
    if registry is None:
        raise HTTPException(status_code=503, detail="Tool registry not initialised")

    try:
        invoke_result = registry.invoke(body.tool, body.params)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ToolExecutionError as exc:
        log.error("Tool execution error", tool=body.tool, error=str(exc.cause), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = invoke_result.result
    if hasattr(result, "__dataclass_fields__"):
        result_dict = dataclasses.asdict(result)
    else:
        result_dict = result

    return JSONResponse({"tool": invoke_result.tool_name, "result": result_dict})


class _RestartBody(BaseModel):
    admin: bool = False


@app.post("/_shutdown")
async def shutdown_server(request: Request) -> JSONResponse:
    if request.app.state.ctx is None:
        raise HTTPException(status_code=503, detail="Server not initialized")
    request_shutdown()
    return JSONResponse({"status": "shutting_down"})


@app.post("/_restart")
async def restart_server(body: _RestartBody, request: Request) -> JSONResponse:
    if request.app.state.ctx is None:
        raise HTTPException(status_code=503, detail="Server not initialized")
    request_restart(admin=body.admin)
    return JSONResponse({"status": "restarting"})


# ---------------------------------------------------------------------------
# Metrics endpoints
# ---------------------------------------------------------------------------


@app.get("/metrics")
async def get_metrics(request: Request) -> JSONResponse:
    collector = request.app.state.metrics_collector
    if collector is None or not collector.enabled:
        raise HTTPException(status_code=404, detail="Metrics collection is disabled")
    snapshot = collector.latest
    if snapshot is None:
        raise HTTPException(status_code=503, detail="No metrics collected yet")
    return JSONResponse(snapshot.model_dump())


@app.get("/metrics/history")
async def get_metrics_history(request: Request, minutes: int = 10) -> JSONResponse:
    collector = request.app.state.metrics_collector
    if collector is None or not collector.enabled:
        raise HTTPException(status_code=404, detail="Metrics collection is disabled")
    cutoff = time.time() - (minutes * 60)
    snapshots = [s.model_dump() for s in collector.history if s.timestamp >= cutoff]
    return JSONResponse({"snapshots": snapshots, "count": len(snapshots)})


@app.get("/metrics/status")
async def get_metrics_status(request: Request) -> JSONResponse:
    collector = request.app.state.metrics_collector
    if collector is None:
        return JSONResponse({"enabled": False, "detail": "Collector not initialised"})
    return JSONResponse(collector.status())


class _MetricsConfigureBody(BaseModel):
    enabled: bool | None = None
    interval: float | None = None
    history_size: int | None = None


@app.post("/metrics/configure")
async def configure_metrics(body: _MetricsConfigureBody, request: Request) -> JSONResponse:
    collector = request.app.state.metrics_collector
    if collector is None:
        raise HTTPException(status_code=503, detail="Collector not initialised")
    result = collector.configure(
        enabled=body.enabled,
        interval=body.interval,
        history_size=body.history_size,
    )
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


async def run_http_server(ctx: ServerContext) -> None:
    """Start uvicorn and shut it down when stop_event is set."""
    uv_config = uvicorn.Config(
        app=app,
        host=ctx.config.http_host,
        port=ctx.config.http_port,
        log_level="warning",
        loop="none",
    )
    server = uvicorn.Server(uv_config)

    serve_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(ctx.stop_event.wait())

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

    log.info("HTTP server stopped")
