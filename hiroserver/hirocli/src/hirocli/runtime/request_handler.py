"""RequestHandler — method registry for request/response messages.

Dispatches inbound UnifiedMessages with message_type "request" to registered
method handlers and **returns** the response UnifiedMessage so the caller
(CommunicationManager) can enqueue it. Returning the response — instead of
calling back into the manager via a back-reference — breaks the previous
``Comm ↔ Request`` cycle.

Request content format (content_type "json"):
    {"method": "channels.list", "params": {}}

Response content format (content_type "json"):
    {"status": "ok", "data": {...}}
    {"status": "error", "error": {"code": "method_not_found", "message": "..."}}
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from hiro_channel_sdk.constants import CONTENT_TYPE_JSON
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger

from .envelope_factory import EnvelopeFactory

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("REQUEST")


class RequestContext:
    """Context passed to method handlers."""

    def __init__(self, ctx: ServerContext, msg: UnifiedMessage) -> None:
        self.workspace_path = ctx.workspace_path
        self.msg = msg
        self.server_ctx = ctx


MethodHandler = Callable[[dict[str, Any], RequestContext], Awaitable[dict[str, Any]]]


class RequestHandler:
    """Dispatches request messages to registered method handlers.

    Usage::

        handler = RequestHandler(ctx)
        handler.register("channels.list", channels_list_handler)
        # CommunicationManager awaits handler.handle(msg) and enqueues the result.

    Method handlers are async functions with signature:
        async def my_handler(params: dict, ctx: RequestContext) -> dict
    """

    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx
        self._methods: dict[str, MethodHandler] = {}

    def register(self, method: str, handler: MethodHandler) -> None:
        """Register an async handler for the given method name."""
        self._methods[method] = handler
        log.info(f"✅ Registered request method: {method}")

    async def handle(self, msg: UnifiedMessage) -> UnifiedMessage:
        """Dispatch a request message and return the response envelope."""
        method, params = _parse_request(msg)
        log.info(
            "Handling request",
            msg_id=msg.routing.id,
            request_id=msg.request_id,
            method=method or "<unparseable>",
        )

        if method is None:
            return EnvelopeFactory.response(
                msg,
                status="error",
                payload={"code": "invalid_request", "message": "Cannot parse request body"},
            )

        handler = self._methods.get(method)
        if handler is None:
            log.warning("Unknown request method", method=method)
            return EnvelopeFactory.response(
                msg,
                status="error",
                payload={"code": "method_not_found", "message": f"Unknown method: {method}"},
            )

        try:
            ctx = RequestContext(self._ctx, msg)
            result = await handler(params, ctx)
            return EnvelopeFactory.response(msg, status="ok", payload=result)
        except Exception as exc:
            log.error(
                "Request handler error",
                method=method,
                error=str(exc),
                exc_info=True,
            )
            return EnvelopeFactory.response(
                msg,
                status="error",
                payload={"code": "internal_error", "message": str(exc)},
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_request(msg: UnifiedMessage) -> tuple[str | None, dict[str, Any]]:
    """Extract method and params from the first JSON content item."""
    for item in msg.content:
        if item.content_type == CONTENT_TYPE_JSON:
            try:
                body = json.loads(item.body)
                method = body.get("method")
                params = body.get("params") or {}
                if isinstance(method, str) and isinstance(params, dict):
                    return method, params
            except (json.JSONDecodeError, AttributeError):
                pass
    return None, {}
