"""OutboundPipeline — queue + worker that delivers messages to the OutboundSink.

The only writer is ``enqueue()`` (used by the CommunicationManager façade and
by AgentManager via ``comm_manager.enqueue_outbound``). The single worker
``run()`` drains the queue, runs an outbound permission check, and dispatches
to the sink.

Asymmetry note: inbound is callback-driven (``InboundPipeline.receive`` is
called directly by ChannelManager), so it has no worker. Symmetrising the
inbound side with its own queue+worker is left for a future PR — see
``docs/communication-manager-refactor.md`` §8.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from hiro_channel_sdk.log_scope_fields import unified_message_log_scope
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger, log_scope

from .comm_log import LOG_OUT, comm_extras, comm_kind, comm_peer_label

if TYPE_CHECKING:
    from .outbound_sink import OutboundSink
    from .server_context import ServerContext

log = Logger.get("OUTBOUND")


def _check_permissions(msg: UnifiedMessage) -> None:
    """Placeholder for outbound user/channel permission checks.

    Will enforce access control rules once the permission system is designed.
    Raise PermissionError to drop the message.
    """


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
                with log_scope(
                    device_id=_out_device_id,
                    msg_id=_out_msg_id,
                    method=_out_method,
                    text_preview=_out_text_preview,
                    traffic_class=_out_traffic_class,
                    traffic_subclass=_out_traffic_subclass,
                ):
                    try:
                        _check_permissions(msg)
                    except PermissionError as exc:
                        log.warning(
                            f"⚠️ {LOG_OUT} Blocked by permission — {self._routing_tag(msg)}",
                            **comm_extras(msg, channel=msg.routing.channel, error=str(exc)),
                        )
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
                    await self._sink.send_to_channel(
                        msg.routing.channel, msg.model_dump(mode="json")
                    )
            finally:
                self.queue.task_done()
