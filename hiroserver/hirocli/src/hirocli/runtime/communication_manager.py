"""CommunicationManager — façade that wires the inbound + outbound pipelines.

After the refactor this module is **pure wiring**. The actual work lives in
small, testable collaborators:

  - ``InboundPipeline``   — validate · permission · route by message_type
  - ``MessageFlow``       — ack + adapter pipeline + post-adapt hook chain
  - ``OutboundPipeline``  — queue · permission · dispatch via OutboundSink
  - ``EnvelopeFactory``   — build server-originated UnifiedMessages
  - ``post_adapt_hooks``  — TranscriptHook, PersistenceHook, EnqueueHook, …

The façade exists so the rest of the runtime keeps a single, stable surface
(``receive``, ``enqueue_outbound``, ``inbound_queue``, ``outbound_queue``,
``serve``) regardless of how the internals are split.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger

from .inbound_pipeline import InboundPipeline
from .message_flow import MessageFlow
from .outbound_pipeline import OutboundPipeline
from .post_adapt_hooks import (
    AdapterErrorLogHook,
    AudioTranscriptHook,
    InboundEnqueueHook,
    PersistenceHook,
    PostAdaptHook,
)

if TYPE_CHECKING:
    from .event_handler import EventHandler
    from .message_adapter import MessageAdapterPipeline
    from .outbound_sink import OutboundSink
    from .request_handler import RequestHandler
    from .server_context import ServerContext

log = Logger.get("COMM_MAN")


class CommunicationManager:
    """Routes messages between channel plugins and the application core.

    Usage::

        pipeline = MessageAdapterPipeline([AudioTranscriptionAdapter(), ...])
        event_handler = EventHandler()
        request_handler = RequestHandler(ctx)
        register_request_methods(request_handler)

        comm = CommunicationManager(
            ctx=ctx,
            sink=channel_manager,             # any OutboundSink
            adapter_pipeline=pipeline,
            event_handler=event_handler,
            request_handler=request_handler,
        )
        channel_manager.set_message_handler(comm.receive)

        await asyncio.gather(..., comm.serve())
        await comm.enqueue_outbound(msg)
    """

    def __init__(
        self,
        ctx: ServerContext,
        sink: OutboundSink,
        adapter_pipeline: MessageAdapterPipeline | None = None,
        event_handler: EventHandler | None = None,
        request_handler: RequestHandler | None = None,
    ) -> None:
        self._ctx = ctx

        self._outbound = OutboundPipeline(ctx=ctx, sink=sink)
        self.inbound_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()

        # Hook order matters:
        #   1. Log per-item adapter errors first so the failure is visible.
        #   2. Emit the transcript event BEFORE persisting so the device gets
        #      the modality mirror even if the DB write later fails.
        #   3. Persist (non-fatal — failures are logged but do not block).
        #   4. Enqueue for the AgentManager (always last; signals "ready").
        post_hooks: list[PostAdaptHook] = [
            AdapterErrorLogHook(ctx),
            AudioTranscriptHook(ctx),
            PersistenceHook(ctx),
            InboundEnqueueHook(self.inbound_queue, ctx),
        ]

        message_flow = MessageFlow(
            ctx=ctx,
            adapter_pipeline=adapter_pipeline,
            post_hooks=post_hooks,
            emit_outbound=self.enqueue_outbound,
        )

        self._inbound = InboundPipeline(
            ctx=ctx,
            message_flow=message_flow,
            emit_outbound=self.enqueue_outbound,
            request_handler=request_handler,
            event_handler=event_handler,
        )

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    @property
    def outbound_queue(self) -> asyncio.Queue[UnifiedMessage]:
        """Backwards-compatible alias for inspection / testing."""
        return self._outbound.queue

    async def receive(self, data: dict[str, Any]) -> None:
        """ChannelManager's ``on_message`` callback target."""
        await self._inbound.receive(data)

    async def enqueue_outbound(self, msg: UnifiedMessage) -> None:
        """Place a message on the outbound queue to be sent to its channel."""
        await self._outbound.enqueue(msg)

    async def serve(self) -> None:
        """Run the outbound worker. Add to ``asyncio.gather`` alongside ChannelManager.

        Inbound is callback-driven (``receive`` is invoked by ChannelManager
        directly), so only outbound has a long-running worker. Symmetrising
        with an inbound queue + worker is tracked in the refactor doc §8.
        """
        log.info("✅ Communication Manager started")
        await self._outbound.run()
