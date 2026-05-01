"""ASGI helpers shared by Hiro's local HTTP servers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
ASGISend = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], ASGIReceive, ASGISend], Awaitable[None]]


class ShutdownCancellationGuard:
    """Suppress expected request cancellations after Hiro shutdown has started."""

    def __init__(self, app: ASGIApp, stop_event: asyncio.Event) -> None:
        self._app = app
        self._stop_event = stop_event

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        try:
            await self._app(scope, receive, send)
        except asyncio.CancelledError:
            # Uvicorn cancels in-flight HTTP/SSE handlers while stopping; once
            # Hiro requested shutdown, that is normal control flow, not an app error.
            if self._stop_event.is_set():
                return
            raise
