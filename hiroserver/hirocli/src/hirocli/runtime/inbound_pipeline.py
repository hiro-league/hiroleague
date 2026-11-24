"""InboundPipeline — validate → permission → dispatch by message_type.

The extension manager's chat handler lands here. ``receive()`` returns
immediately in all cases:

  - ``message`` → emits the immediate ``message.received`` ack, then hands
    the message to the AgentManager via the ``run_message`` callback.
  - ``request`` → dispatched to ``RequestHandler.handle`` in a background task;
    the returned response is enqueued by the task wrapper.
  - ``event``   → dispatched to ``EventHandler.handle`` in a background task.
  - unknown     → routing-error response is enqueued and the message is dropped.

The pipeline owns no message-flow state; the agent graph + outbound subscribers
own all post-validation work.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from hiro_channel_sdk.constants import (
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_STREAM,
)
from hiro_channel_sdk.log_scope_fields import unified_message_log_scope
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons import tasks
from hiro_commons.log import Logger, log_scope

from .chat_writer import NotAllowed, conversation_for, stamp, writer_of
from .comm_log import LOG_IN, comm_extras, comm_kind, comm_peer_label
from .envelope_factory import EnvelopeFactory

if TYPE_CHECKING:
    from .event_handler import EventHandler
    from .request_handler import RequestHandler
    from .server_context import ServerContext


log = Logger.get("INBOUND")


# Callback signature: dispatch a validated inbound ``message`` to the agent.
# Implemented by ``CommunicationManager._dispatch_to_agent``.
RunMessage = Callable[..., Awaitable[None]]
EmitOutbound = Callable[[UnifiedMessage], Awaitable[None]]


def _admit(workspace_path: Path, msg: UnifiedMessage, person_id: str | None) -> None:
    """Who wrote a chat ``message``, whether they may talk, and its conversation (Permissions phase 3): raises
    :class:`NotAllowed` before anything is kept or acknowledged. Requests and events pass: a device's requests are
    checked per method (request_methods.py)."""
    if msg.message_type != MESSAGE_TYPE_MESSAGE:
        return
    writer = writer_of(workspace_path, msg, person_id=person_id)
    stamp(msg, writer, conversation_for(workspace_path, msg, writer))


class InboundPipeline:
    """Routes inbound UnifiedMessages by ``message_type``."""

    def __init__(
        self,
        ctx: "ServerContext",
        run_message: RunMessage,
        emit_outbound: EmitOutbound,
        request_handler: "RequestHandler | None" = None,
        event_handler: "EventHandler | None" = None,
    ) -> None:
        self._ctx = ctx
        self._run_message = run_message
        self._emit = emit_outbound
        self._request_handler = request_handler
        self._event_handler = event_handler

    def _routing_tag(self, msg: UnifiedMessage) -> str:
        return f"{comm_peer_label(msg, self._ctx)} · {comm_kind(msg)}"

    async def receive(
        self,
        data: dict[str, Any],
        *,
        await_message_flow: bool = False,
        person_id: str | None = None,
    ) -> None:
        """Validate the raw dict, check who wrote it, and dispatch by type.

        ``await_message_flow=True`` blocks ``message`` payloads until the
        inbound-persistence subscriber finishes. Other message types ignore
        the flag. ``person_id`` is the writer an in-process sender hands in (the
        admin's signed-in person; "" for the owner, the command line's).
        """
        try:
            msg = UnifiedMessage.model_validate(data)
        except Exception as exc:
            log.warning(f"⚠️ {LOG_IN} Dropping malformed message", error=str(exc))
            return

        try:
            # Off the loop: it reads the family list and the conversations, and may make a person's first one
            await asyncio.to_thread(_admit, self._ctx.workspace_path, msg, person_id)
        except NotAllowed as exc:
            # A stranger, or someone who may not talk: nothing is kept, acknowledged or answered
            log.info(
                f"{LOG_IN} Message dropped — {exc.reason} · {self._routing_tag(msg)}",
                **comm_extras(msg, channel=msg.routing.channel),
            )
            return
        except Exception as exc:
            # Without a writer and a conversation the message can't be threaded or kept
            log.error(
                f"❌ {LOG_IN} Could not tell who wrote the message — dropping",
                **comm_extras(msg, channel=msg.routing.channel, error=str(exc)),
                exc_info=True,
            )
            return

        (
            _dev, _mid, _meth, _pv, _tc, _tsc,
        ) = unified_message_log_scope(msg, direction="inbound")
        with log_scope(
            device_id=_dev, msg_id=_mid, method=_meth,
            text_preview=_pv, traffic_class=_tc, traffic_subclass=_tsc,
        ):
            await self._dispatch(msg, await_message_flow=await_message_flow)

    async def _dispatch(
        self,
        msg: UnifiedMessage,
        *,
        await_message_flow: bool,
    ) -> None:
        match msg.message_type:
            case _ if msg.message_type == MESSAGE_TYPE_MESSAGE:
                # Immediate delivery ack so the device shows a tick before
                # the graph even starts.
                await self._emit(EnvelopeFactory.ack_event(msg))
                log.fineinfo(
                    f"{LOG_IN} message acked — {self._routing_tag(msg)}",
                    **comm_extras(msg, channel=msg.routing.channel),
                )
                await self._run_message(msg, await_persisted=await_message_flow)

            case _ if msg.message_type == MESSAGE_TYPE_REQUEST:
                await self._dispatch_request(msg)

            case _ if msg.message_type == MESSAGE_TYPE_STREAM:
                log.info(
                    f"{LOG_IN} stream frame ignored (download-only) — {self._routing_tag(msg)}",
                    **comm_extras(msg),
                )

            case _ if msg.message_type == MESSAGE_TYPE_EVENT:
                await self._dispatch_event(msg)

            case _:
                log.warning(
                    f"⚠️ {LOG_IN} Unknown message_type, dropping — {self._routing_tag(msg)}",
                    **comm_extras(msg, message_type=msg.message_type),
                )
                await self._emit(
                    EnvelopeFactory.routing_error_response(
                        msg, f"Unknown message_type: {msg.message_type}",
                    )
                )

    async def _dispatch_request(self, msg: UnifiedMessage) -> None:
        if self._request_handler is None:
            log.warning(
                f"⚠️ {LOG_IN} No RequestHandler, dropping — {self._routing_tag(msg)}",
                **comm_extras(msg),
            )
            return

        tasks.keep(
            self._safe_handle_request(msg),
            name=f"request-{msg.routing.id}",
        )

    async def _safe_handle_request(self, msg: UnifiedMessage) -> None:
        try:
            response = await self._request_handler.handle(msg, emit_outbound=self._emit)
            if response is not None:
                await self._emit(response)
        except Exception as exc:
            log.error(
                f"❌ {LOG_IN} RequestHandler failed — {self._routing_tag(msg)}",
                **comm_extras(msg, error=str(exc)),
                exc_info=True,
            )

    async def _dispatch_event(self, msg: UnifiedMessage) -> None:
        if self._event_handler is None:
            log.info(
                f"{LOG_IN} Event dropped (no EventHandler) — {self._routing_tag(msg)}",
                event_type=msg.event.type if msg.event else None,
            )
            return

        tasks.keep(
            self._safe_handle_event(msg),
            name=f"event-{msg.routing.id}",
        )

    async def _safe_handle_event(self, msg: UnifiedMessage) -> None:
        try:
            await self._event_handler.handle(msg)
        except Exception as exc:
            log.error(
                f"❌ {LOG_IN} EventHandler failed — {self._routing_tag(msg)}",
                **comm_extras(msg, error=str(exc)),
                exc_info=True,
            )
