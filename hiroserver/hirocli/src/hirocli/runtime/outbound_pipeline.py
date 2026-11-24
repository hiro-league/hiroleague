"""OutboundPipeline — queue + worker that delivers messages to the OutboundSink.

The only writer is ``enqueue()`` (used by the CommunicationManager façade and
by AgentManager via ``comm_manager.enqueue_outbound``). The single worker
``run()`` drains the queue, runs an outbound permission check, and dispatches
to the sink.

Asymmetry note: inbound is callback-driven (``InboundPipeline.receive`` is
called directly by ExtensionManager), so it has no worker. Symmetrising the
inbound side with its own queue+worker is left for a future PR — see
``docs/communication-manager-refactor.md`` §8.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from hiro_channel_sdk import message_story
from hiro_channel_sdk.log_scope_fields import unified_message_log_scope
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hiro_commons.log import Logger, log_scope
from hiro_commons.logging_foundation import story

from ..domain.conversation_channel import CHAT_CHANNEL_ID_METADATA_KEY

from .comm_log import LOG_OUT, comm_extras, comm_kind, comm_peer_label

if TYPE_CHECKING:
    from .outbound_sink import OutboundSink
    from .server_context import ServerContext

log = Logger.get("OUTBOUND")


async def _device_targets(ctx: ServerContext, msg: UnifiedMessage) -> list[str] | None:
    """The devices a frame for the devices channel goes to (Permissions phase 3), or None to send it as it is.

    A frame that names its device goes there. One that names none would reach every device through the gateway, so it
    goes to the connected devices of its conversation's person instead, and to no device when it names no
    conversation.
    """
    if msg.routing.channel != MANDATORY_CHANNEL_NAME or msg.routing.recipient_id:
        return None
    conversation = (msg.routing.metadata or {}).get(CHAT_CHANNEL_ID_METADATA_KEY)
    if not conversation:
        log.warning(f"⚠️ {LOG_OUT} Not sent — a frame for every device names no conversation", **comm_extras(msg))
        return []
    return await asyncio.to_thread(ctx.device_targeting.for_conversation, conversation)


class OutboundPipeline:
    """FIFO queue of UnifiedMessages dispatched to a single OutboundSink."""

    def __init__(self, ctx: ServerContext, sink: OutboundSink) -> None:
        self._ctx = ctx
        self._sink = sink
        self.queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()

    def _routing_tag(self, msg: UnifiedMessage) -> str:
        return f"{comm_peer_label(msg, self._ctx)} · {comm_kind(msg)}"

    async def enqueue(self, msg: UnifiedMessage) -> None:
        """Place a message on the outbound queue. Returns once enqueued."""
        (
            _out_device_id,
            _out_msg_id,
            _out_method,
            _out_text_preview,
            _out_traffic_class,
            _out_traffic_subclass,
        ) = unified_message_log_scope(msg, direction="outbound")
        with log_scope(
            device_id=_out_device_id,
            msg_id=_out_msg_id,
            method=_out_method,
            text_preview=_out_text_preview,
            traffic_class=_out_traffic_class,
            traffic_subclass=_out_traffic_subclass,
        ):
            # The queue breaks the story's context: the message carries the step that queued it (the agent's run, the
            # server's receive), and sending it is a step under that one.
            story.inject(msg.routing.metadata)
            await self.queue.put(msg)
            # Per-hop queue visibility is verbose; higher layers (e.g. Sent on
            # the channel) retain INFO for message-flow milestones. Use
            # fineinfo so default INFO logs stay readable.
            log.fineinfo(
                f"{LOG_OUT} Queued — {self._routing_tag(msg)}",
                **comm_extras(
                    msg,
                    channel=msg.routing.channel,
                    items=len(msg.content),
                ),
            )

    async def run(self) -> None:
        """Continuously drain the queue and dispatch to the sink."""
        while True:
            msg = await self.queue.get()
            try:
                # Re-open scope here: the queue hop breaks the asyncio task context.
                # Outbound direction: device_id is the recipient.
                # Events with ref_id (transcript, voiced) carry the original msg_id.
                (
                    _out_device_id,
                    _out_msg_id,
                    _out_method,
                    _out_text_preview,
                    _out_traffic_class,
                    _out_traffic_subclass,
                ) = unified_message_log_scope(msg, direction="outbound")
                with message_story.hop("server.send", msg.routing.metadata, _out_msg_id, area="OUTBOUND"), log_scope(
                    device_id=_out_device_id,
                    msg_id=_out_msg_id,
                    method=_out_method,
                    text_preview=_out_text_preview,
                    traffic_class=_out_traffic_class,
                    traffic_subclass=_out_traffic_subclass,
                ):
                    try:
                        targets = await _device_targets(self._ctx, msg)
                    except Exception as exc:
                        # One frame whose devices can't be read never stops the queue; it goes to no device
                        log.error(f"❌ {LOG_OUT} Not sent — its devices couldn't be read", **comm_extras(msg, error=str(exc)),
                                  exc_info=True)
                        continue

                    # See ``enqueue`` — same rationale: avoid duplicate INFO per hop.
                    log.fineinfo(
                        f"{LOG_OUT} Dispatching — {self._routing_tag(msg)}",
                        **comm_extras(
                            msg,
                            channel=msg.routing.channel,
                            items=len(msg.content),
                        ),
                    )
                    if targets is None:
                        await self._sink.send_to_channel(msg.routing.channel, msg.model_dump(mode="json"))
                        continue
                    # One frame per device of the conversation's person
                    for device_id in targets:
                        if device_id == msg.routing.sender_id:
                            continue  # a device's own message, mirrored: it has it already
                        frame = msg.model_dump(mode="json")
                        frame["routing"]["recipient_id"] = device_id
                        await self._sink.send_to_channel(msg.routing.channel, frame)
            finally:
                self.queue.task_done()
