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

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
CALLER_DEVICE = "device"        # the phone app, through a channel (the devices plugin)
CALLER_EXTENSION = "extension"  # an app signed in on the extension socket
CALLER_CHANNEL = "channel"      # a channel plugin's own request (none open to it yet)
DEVICES_ONLY: frozenset[str] = frozenset({CALLER_DEVICE})
EXTENSIONS_ONLY: frozenset[str] = frozenset({CALLER_EXTENSION})
ALL_CALLERS: frozenset[str] = frozenset({CALLER_DEVICE, CALLER_EXTENSION})


# What a device's request needs (Permissions phase 3): a core permission (feature, action) its person's roles hold,
# for their own things or everyone's; ANY_DEVICE for what every paired device of a known person may ask (its problems,
# the core's name). A method that names none answers the owner's devices only.
DeviceRight = tuple[str, str] | None
ANY_DEVICE: DeviceRight = None
OWNER_ONLY = ("", "")


@dataclass(frozen=True)
class DeviceAsker:
    """The person a device's request is answered for: the device's own (a device shows only its person's
    conversations, whatever their reach)."""

    person_id: str  # "" = no family list yet: the owner
    user_id: int  # their chat user: their conversations are this user's


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
        # Set for a device's request (Permissions phase 3): handlers answer for this person only
        self.asker: DeviceAsker | None = None

    def own_user(self) -> int | None:
        """The chat user a device's request is scoped to; None for an app's (it reads no conversation)."""
        return self.asker.user_id if self.asker is not None else None


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
        self._device_rights: dict[str, DeviceRight] = {}

    def register(
        self,
        method: str,
        handler: MethodHandler,
        *,
        callers: frozenset[str] = DEVICES_ONLY,
        device_right: DeviceRight = OWNER_ONLY,
    ) -> None:
        """Register an async handler for the given method name, who may call it, and what a device's person needs."""
        self._methods[method] = handler
        self._callers[method] = callers
        self._device_rights[method] = device_right
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
            if caller == CALLER_DEVICE:
                ctx.asker = await asyncio.to_thread(
                    device_asker, self._ctx.workspace_path, msg.routing.sender_id or "",
                    self._device_rights.get(method, OWNER_ONLY),
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


def gate(system: str, code: str, *, write: bool = True, fakes: bool = False) -> str:
    """Refuse a request for an outside system this place may not reach that way (hiro_commons.switchboard: a test
    environment's AI, voices or WhatsApp off, or fake where the handler has no stand-in), with the method's own
    error code and words that name the system and the place. Else the system's mode: a handler with a stand-in
    (`fakes`) answers from it when the mode is "fake". In live and env0 everything is real."""
    from hiro_commons import switchboard

    try:
        return switchboard.check(system, write=write, fakes=fakes)
    except switchboard.Refused as exc:
        raise RequestRefused(code, str(exc)) from exc


def device_asker(workspace_path: Any, device_id: str, right: DeviceRight) -> DeviceAsker:
    """The person a device's request is for, if their roles hold what the method needs; else :class:`RequestRefused`
    (Permissions phase 3). The owner's roles hold every right; a right for their own things is enough, since a device
    is answered for its own person only."""
    from hiro_channel_sdk.access import allowed

    from ..domain.access import admin_access
    from ..domain.core_features import CORE_BY_ID
    from ..domain.talkers import device_owner, is_owner

    person, user_id = device_owner(workspace_path, device_id)
    if user_id is None:
        raise RequestRefused("not_allowed", "This device belongs to nobody in the family list.")
    if person is None:  # no family list yet: the owner's
        return DeviceAsker(person_id="", user_id=user_id)
    if right is ANY_DEVICE:
        return DeviceAsker(person_id=person.person_id, user_id=user_id)
    if right == OWNER_ONLY:
        if is_owner(person):
            return DeviceAsker(person_id=person.person_id, user_id=user_id)
        raise RequestRefused("not_allowed", "Only the owner's devices can ask this.")
    feature, action = right
    roles = admin_access(workspace_path, person.role_ids).roles
    if not allowed(roles, feature, action, CORE_BY_ID, asker=person.person_id, owners=[person.person_id]):
        raise RequestRefused("not_allowed", f"{person.name}'s roles don't include {feature}: {action}.")
    return DeviceAsker(person_id=person.person_id, user_id=user_id)

