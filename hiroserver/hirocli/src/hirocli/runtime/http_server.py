"""FastAPI HTTP server for hirocli.

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
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from hiro_commons.log import Logger
from hiro_commons.process import is_running, read_pid
from pydantic import BaseModel

from ..domain.config import Config, load_state
from ..constants import APP_NAME, PID_FILENAME
from ..tools.registry import ToolExecutionError, ToolNotFoundError

log = Logger.get("HTTP")

app = FastAPI(title=APP_NAME, version="0.1.0", docs_url=None, redoc_url=None)

# Defaults — overwritten by server_process.py before the server starts.
app.state.workspace_path = None
app.state.stop_event = None
app.state.tool_registry = None
app.state.channel_info_provider = None
app.state.metrics_collector = None
app.state.restart_requested = False
app.state.restart_admin = False


def request_shutdown() -> None:
    """Trigger graceful shutdown with a short delay so HTTP responses can flush."""
    stop_event = app.state.stop_event
    if stop_event is not None:
        asyncio.get_running_loop().call_later(0.5, stop_event.set)


def request_restart(admin: bool = False) -> None:
    """Trigger restart: graceful shutdown + respawn on exit."""
    app.state.restart_requested = True
    app.state.restart_admin = admin
    request_shutdown()


@app.get("/status")
async def get_status(request: Request) -> JSONResponse:
    workspace_path = request.app.state.workspace_path
    assert workspace_path is not None, "workspace_path not initialised"
    state = load_state(workspace_path)
    pid = read_pid(workspace_path, PID_FILENAME)
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
    if request.app.state.stop_event is None:
        raise HTTPException(status_code=503, detail="Server not initialized")
    request_shutdown()
    return JSONResponse({"status": "shutting_down"})


@app.post("/_restart")
async def restart_server(body: _RestartBody, request: Request) -> JSONResponse:
    if request.app.state.stop_event is None:
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


async def run_http_server(config: Config, stop_event: asyncio.Event) -> None:
    """Start uvicorn and shut it down when stop_event is set."""
    uv_config = uvicorn.Config(
        app=app,
        host=config.http_host,
        port=config.http_port,
        log_level="warning",
        loop="none",
    )
    server = uvicorn.Server(uv_config)

    serve_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(stop_event.wait())

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
