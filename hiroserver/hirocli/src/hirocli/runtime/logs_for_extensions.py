"""Apps send their log lines to the core: the ``logs.send`` request (the logging plan, phase 5).

Each app keeps its own file first and sends the lines at INFO and up; the core keeps them in its log store
(services/log_store.py), in the stream ``app-<the app's name>``, beside its own files, so the log tools answer across
every app. Extensions only. The app's name is the one the core knows it by (design rule 6), never one it sends.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hiro_channel_sdk.constants import METHOD_LOGS_SEND

from ..services import log_store
from .ai_for_extensions import _caller_name
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused

INVALID = "invalid"
MAX_LINES = 2000  # per batch: the app's sender sends 500 at most


async def handle_logs_send(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    items = params.get("lines")
    if not isinstance(items, list):
        raise RequestRefused(INVALID, "lines is required: [[place, line], ...].")
    if len(items) > MAX_LINES:
        raise RequestRefused(INVALID, f"At most {MAX_LINES} lines in one batch.")
    stream = log_store.app_stream(await _caller_name(ctx))
    last = await asyncio.to_thread(log_store.receive, stream, items, restart=params.get("restart") is True)
    return {"last": last}


LOGS_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_LOGS_SEND, handle_logs_send, EXTENSIONS_ONLY),
)
