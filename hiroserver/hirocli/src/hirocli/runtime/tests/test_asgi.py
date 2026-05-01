from __future__ import annotations

import asyncio
from typing import Any

import pytest

from hirocli.runtime.asgi import ShutdownCancellationGuard


async def _cancelled_app(
    scope: dict[str, Any],
    receive: Any,
    send: Any,
) -> None:
    raise asyncio.CancelledError


async def _receive() -> dict[str, Any]:
    return {"type": "http.disconnect"}


async def _send(message: dict[str, Any]) -> None:
    return None


@pytest.mark.asyncio
async def test_shutdown_guard_suppresses_cancelled_error_after_stop_event() -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    app = ShutdownCancellationGuard(_cancelled_app, stop_event)

    await app({"type": "http"}, _receive, _send)


@pytest.mark.asyncio
async def test_shutdown_guard_reraises_cancelled_error_before_stop_event() -> None:
    stop_event = asyncio.Event()
    app = ShutdownCancellationGuard(_cancelled_app, stop_event)

    with pytest.raises(asyncio.CancelledError):
        await app({"type": "http"}, _receive, _send)
