"""RequestHandler — method registry for request/response messages.

Dispatches inbound UnifiedMessages with message_type "request" to registered
method handlers, builds a response UnifiedMessage, and enqueues it outbound.

Request content format (content_type "json"):
    {"method": "channels.list", "params": {}}

Response content format (content_type "json"):
    {"status": "ok", "data": {...}}
    {"status": "error", "error": {"code": "method_not_found", "message": "..."}}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol

from hiro_channel_sdk.constants import CONTENT_TYPE_JSON, MESSAGE_TYPE_RESPONSE
from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from hiro_commons.log import Logger

if TYPE_CHECKING:
    from .communication_manager import CommunicationManager

log = Logger.get("REQUEST")


class RequestContext:
    """Context passed to method handlers."""

    def __init__(self, workspace_path: Path, msg: UnifiedMessage) -> None:
        self.workspace_path = workspace_path
        self.msg = msg


MethodHandler = Callable[[dict[str, Any], RequestContext], Awaitable[dict[str, Any]]]


class RequestHandler:
    """Dispatches request messages to registered method handlers.

    Usage::

        handler = RequestHandler(comm_manager, workspace_path)
        handler.register("channels.list", channels_list_handler)
        # wire into CommunicationManager at startup

    Method handlers are async functions with signature:
        async def my_handler(params: dict, ctx: RequestContext) -> dict
    """

    def __init__(
        self, comm_manager: CommunicationManager, workspace_path: Path
    ) -> None:
        self._comm = comm_manager
        self._workspace_path = workspace_path
        self._methods: dict[str, MethodHandler] = {}

    def register(self, method: str, handler: MethodHandler) -> None:
        """Register an async handler for the given method name."""
        self._methods[method] = handler
        log.info("Registered request method", method=method)

    async def handle(self, msg: UnifiedMessage) -> None:
        """Dispatch a request message and enqueue the response."""
        method, params = _parse_request(msg)
        log.info(
            "Handling request",
            msg_id=msg.routing.id,
            request_id=msg.request_id,
            method=method or "<unparseable>",
        )

        if method is None:
            response = _build_response(
                msg,
                status="error",
                payload={"code": "invalid_request", "message": "Cannot parse request body"},
            )
            await self._comm.enqueue_outbound(response)
            return

        handler = self._methods.get(method)
        if handler is None:
            log.warning("Unknown request method", method=method)
            response = _build_response(
                msg,
                status="error",
                payload={"code": "method_not_found", "message": f"Unknown method: {method}"},
            )
            await self._comm.enqueue_outbound(response)
            return

        try:
            ctx = RequestContext(self._workspace_path, msg)
            result = await handler(params, ctx)
            response = _build_response(msg, status="ok", payload=result)
        except Exception as exc:
            log.error(
                "Request handler error",
                method=method,
                error=str(exc),
                exc_info=True,
            )
            response = _build_response(
                msg,
                status="error",
                payload={"code": "internal_error", "message": str(exc)},
            )

        await self._comm.enqueue_outbound(response)


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


def _build_response(
    request: UnifiedMessage,
    *,
    status: str,
    payload: dict[str, Any],
) -> UnifiedMessage:
    body: dict[str, Any]
    if status == "ok":
        body = {"status": "ok", "data": payload}
    else:
        body = {"status": "error", "error": payload}

    return UnifiedMessage(
        message_type=MESSAGE_TYPE_RESPONSE,
        request_id=request.request_id,
        routing=MessageRouting(
            channel=request.routing.channel,
            direction="outbound",
            sender_id="server",
            recipient_id=request.routing.sender_id,
            # Preserve metadata (e.g. channel_id) so the channel plugin can
            # route the response back to the originating device/conversation.
            metadata=request.routing.metadata,
        ),
        content=[ContentItem(content_type=CONTENT_TYPE_JSON, body=json.dumps(body))],
    )
