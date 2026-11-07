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
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import CONTENT_TYPE_JSON
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger

from .envelope_factory import EnvelopeFactory

if TYPE_CHECKING:
    from .resource_versioning import ResourceVersionStore
    from .server_context import ServerContext

log = Logger.get("REQUEST")

EmitOutbound = Callable[[UnifiedMessage], Awaitable[None]]

# Who sent a request. Each method says which callers may use it, so an extension
# that is signed in can't read chat history just because it is connected.
CALLER_DEVICE = "device"        # the app, through a channel (the devices plugin)
CALLER_EXTENSION = "extension"  # a program signed in on the extension socket
DEVICES_ONLY: frozenset[str] = frozenset({CALLER_DEVICE})
EXTENSIONS_ONLY: frozenset[str] = frozenset({CALLER_EXTENSION})
ALL_CALLERS: frozenset[str] = frozenset({CALLER_DEVICE, CALLER_EXTENSION})


class RequestRefused(Exception):
    """Raised by a handler to answer with an error the caller can act on.

    ``code`` is a short machine code (e.g. ``invalid_params``, ``whatsapp_not_connected``);
    ``message`` is meant for people.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class RequestContext:
    """Context passed to method handlers."""

    def __init__(
        self,
        ctx: ServerContext,
        msg: UnifiedMessage,
        *,
        resource_versions: ResourceVersionStore | None = None,
        emit_outbound: EmitOutbound | None = None,
    ) -> None:
        self.workspace_path = ctx.workspace_path
        self.msg = msg
        self.server_ctx = ctx
        self.resource_versions = resource_versions
        self.emit_outbound = emit_outbound


MethodHandler = Callable[[dict[str, Any], RequestContext], Awaitable[dict[str, Any] | None]]


class RequestHandler:
    """Dispatches request messages to registered method handlers.

    Usage::

        handler = RequestHandler(ctx)
        handler.register("channels.list", channels_list_handler)
        # CommunicationManager awaits handler.handle(msg) and enqueues the result.

    Method handlers are async functions::

        async def my_handler(params: dict, ctx: RequestContext) -> dict[str, Any] | None
    """

    def __init__(
        self,
        ctx: ServerContext,
        resource_versions: ResourceVersionStore | None = None,
    ) -> None:
        self._ctx = ctx
        self._resource_versions = resource_versions
        self._methods: dict[str, MethodHandler] = {}
        self._callers: dict[str, frozenset[str]] = {}

    def register(
        self,
        method: str,
        handler: MethodHandler,
        *,
        callers: frozenset[str] = DEVICES_ONLY,
    ) -> None:
        """Register an async handler for the given method name and who may call it."""
        self._methods[method] = handler
        self._callers[method] = callers
        log.fineinfo(f"✅ Registered request method: {method}", callers=sorted(callers))

    async def handle(
        self,
        msg: UnifiedMessage,
        *,
        emit_outbound: EmitOutbound,
        caller: str = CALLER_DEVICE,
    ) -> UnifiedMessage | None:
        """Dispatch a request message and return the response envelope, if any.

        Handlers may emit additional envelopes via ``RequestContext.emit_outbound`` and
        return ``None`` (e.g. ``files.get`` ack + stream + terminal already emitted).
        A method the caller may not use answers ``method_not_found`` (not "forbidden",
        so a caller can't probe which methods exist for others).
        """
        method, params = _parse_request(msg)
        log.fineinfo(
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
        if handler is not None and caller not in self._callers.get(method, DEVICES_ONLY):
            log.warning("Request method not open to this caller", method=method, caller=caller)
            handler = None
        if handler is None:
            log.warning("Unknown request method", method=method)
            return EnvelopeFactory.response(
                msg,
                status="error",
                payload={"code": "method_not_found", "message": f"Unknown method: {method}"},
            )

        try:
            ctx = RequestContext(
                self._ctx,
                msg,
                resource_versions=self._resource_versions,
                emit_outbound=emit_outbound,
            )
            result = await handler(params, ctx)
            if result is None:
                return None
            return EnvelopeFactory.response(msg, status="ok", payload=result)
        except RequestRefused as exc:
            # An expected "no" (e.g. WhatsApp isn't linked): the caller gets the code
            # and message; logged as a warning, not as a crash with a traceback.
            log.warning(f"⚠️ Request refused — {method} · {exc.code}", error=exc.message)
            return EnvelopeFactory.response(
                msg,
                status="error",
                payload={"code": exc.code, "message": exc.message},
            )
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
