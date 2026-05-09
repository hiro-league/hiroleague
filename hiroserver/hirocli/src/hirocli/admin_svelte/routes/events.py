"""Long-lived streaming endpoints (SSE). Kept separate from CRUD routers."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from hirocli.admin_svelte.status_snapshot import _status_snapshot
from hirocli.admin_svelte.streaming_constants import STATUS_STREAM_INTERVAL_SECONDS

events_router = APIRouter()


@events_router.get("/events/status")
async def stream_status_events(
    request: Request,
    workspace: str | None = None,
) -> StreamingResponse:
    async def events():
        last_payload = ""
        try:
            while not await request.is_disconnected():
                snapshot = await run_in_threadpool(_status_snapshot, workspace)
                payload = json.dumps(snapshot, separators=(",", ":"))
                if payload != last_payload:
                    yield f"event: status\ndata: {payload}\n\n"
                    last_payload = payload
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(STATUS_STREAM_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            # Browser tab closes and server shutdown both cancel SSE streams.
            return

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
