"""CommunicationManager — wire + outbound subscriber facade.

After the agent-graph redesign this module is a tiny composition root:

  - ``InboundPipeline``      — validate · permission · route by message_type.
  - ``OutboundPipeline``     — queue · permission · dispatch via OutboundSink.
  - ``GraphEventSubscriber`` — bridges agent-graph events to outbound
    envelopes + storage side effects (persist, mirror, transcribed, text
    reply, voiced, error fallback).

The old ``MessageFlow``, ``MessageAdapterPipeline``, post-adapt hooks, and
``inbound_queue`` are gone. All STT/vision/TTS work lives inside the
agent graph; outbound side effects subscribe to the graph events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger

from .graph_event_subscriber import GraphEventSubscriber
from .inbound_pipeline import InboundPipeline
from .outbound_pipeline import OutboundPipeline
from .server_context import ServerContext

if TYPE_CHECKING:
    from .agent_manager import AgentManager
    from .event_handler import EventHandler
    from .outbound_sink import OutboundSink
    from .request_handler import RequestHandler

log = Logger.get("COMM_MAN")


class CommunicationManager:
    """Routes messages between channel plugins and the agent graph runner."""

    def __init__(
        self,
        ctx: ServerContext,
        sink: "OutboundSink",
        event_handler: "EventHandler | None" = None,
        request_handler: "RequestHandler | None" = None,
    ) -> None:
        self._ctx = ctx
        self._outbound = OutboundPipeline(ctx=ctx, sink=sink)
        # Subscribers attach to graph events; the AgentManager forwards
        # ``custom`` stream entries to ``graph_subscriber.dispatch``.
        self.graph_subscriber = GraphEventSubscriber(
            ctx=ctx,
            emit_outbound=self.enqueue_outbound,
        )
        self._agent_manager: "AgentManager | None" = None
        self._inbound = InboundPipeline(
            ctx=ctx,
            run_message=self._dispatch_to_agent,
            emit_outbound=self.enqueue_outbound,
            request_handler=request_handler,
            event_handler=event_handler,
        )

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def attach_agent_manager(self, agent_manager: "AgentManager") -> None:
        """Wire the agent runner. Called by the composition root after build."""
        self._agent_manager = agent_manager

    @property
    def ctx(self) -> ServerContext:
        return self._ctx

    @property
    def outbound_queue(self):
        """Backwards-compatible alias kept for tests / inspection."""
        return self._outbound.queue

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def receive(
        self,
        data: dict[str, Any],
        *,
        await_message_flow: bool = False,
    ) -> None:
        """Channel Manager's ``on_message`` callback target.

        ``await_message_flow=True`` blocks until the inbound persistence
        subscriber has run for ``message`` payloads. Used by synthetic
        injectors (Admin UI / CLI ``message_send``) so a follow-up HTTP
        refresh sees the persisted row.
        """
        await self._inbound.receive(data, await_message_flow=await_message_flow)

    async def enqueue_outbound(self, msg: UnifiedMessage) -> None:
        """Place a message on the outbound queue."""
        await self._outbound.enqueue(msg)

    async def serve(self) -> None:
        """Run the outbound worker. Add to ``asyncio.gather`` alongside ChannelManager."""
        log.info("✅ Communication Manager started")
        await self._outbound.run()

    # ------------------------------------------------------------------
    # Internal — InboundPipeline calls this for ``message_type == "message"``.
    # ------------------------------------------------------------------

    async def _dispatch_to_agent(
        self,
        msg: UnifiedMessage,
        *,
        await_persisted: bool,
    ) -> None:
        """Hand a validated inbound message to the agent graph.

        ``await_persisted=True`` blocks until the inbound persistence
        subscriber finishes (used by ``message_send``). The graph keeps
        running in the background after the event fires.
        """
        import asyncio

        if self._agent_manager is None:
            log.error(
                "❌ AgentManager not attached — message dropped",
                msg_id=msg.routing.id,
            )
            return

        if not await_persisted:
            asyncio.create_task(
                self._agent_manager.handle(msg),
                name=f"agent-{msg.routing.id}",
            )
            return

        persisted = asyncio.Event()
        asyncio.create_task(
            self._agent_manager.handle(msg, persisted_event=persisted),
            name=f"agent-{msg.routing.id}",
        )
        await persisted.wait()
