"""Runtime readiness probe.

The admin UI binds its port very early in server startup (right after the DBs
exist) so the operator gets a fast Time-To-Interactive. A few admin actions —
notably ``chat send``, which goes through ``post_invoke_sync`` to the main
HiroServer HTTP API — depend on the main HTTP server having bound its port.

This endpoint reports whether the main HiroServer is listening on
``ctx.config.http_port`` so the frontend can surface a friendly "server is
starting…" banner while the long-running setup (TTS load, AgentManager,
KnowledgeManager) finishes in the background.

Only the localhost TCP port is probed (no HTTP roundtrip needed). The probe is
short (250 ms timeout) and only runs when the frontend asks for it; the result
is not cached because the readiness state can flip in either direction
(start → ready → restart → not ready).
"""

from __future__ import annotations

import socket
from typing import Any

from fastapi import APIRouter, Request
from hiro_commons.log import Logger

runtime_router = APIRouter()

log = Logger.get("ADMIN.RUNTIME")


def _main_http_listening(http_port: int, *, timeout_s: float = 0.25) -> bool:
    """Return True when something is accepting TCP on ``127.0.0.1:http_port``.

    Uses a non-HTTP TCP connect so we don't pay request parsing latency and
    don't confuse the readiness check with application-level errors.
    """
    try:
        with socket.create_connection(("127.0.0.1", http_port), timeout=timeout_s):
            return True
    except (OSError, ValueError):
        return False


@runtime_router.get("/runtime/status")
async def runtime_status(request: Request) -> dict[str, Any]:
    """Report which late-bound runtime pieces are live.

    Response shape (stable; frontend polls until ``ready`` is true):

        {
          "ok": true,
          "error": null,
          "data": {
            "ready": bool,             # convenience: all critical pieces up
            "main_http_listening": bool,
            "admin_port": int,
            "http_port": int,
          }
        }
    """
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        return {
            "ok": False,
            "error": "Admin app has no ServerContext attached.",
            "data": None,
        }

    http_port = int(ctx.config.http_port)
    main_ready = _main_http_listening(http_port)

    return {
        "ok": True,
        "error": None,
        "data": {
            "ready": main_ready,
            "main_http_listening": main_ready,
            "admin_port": int(ctx.config.admin_port),
            "http_port": http_port,
        },
    }
