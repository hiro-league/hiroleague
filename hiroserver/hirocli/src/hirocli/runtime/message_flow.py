"""MessageFlow — orchestrates the inbound ``message`` type.

Owns the two-phase handling that ``CommunicationManager`` used to do inline:

  1. Synchronous: emit the ``message.received`` ack so the device gets a
     delivery indicator immediately.
  2. Detached: spawn a background task that runs the adapter pipeline and
     then walks the post-adapt hook chain.

The router never blocks on adaptation — even if transcription takes seconds,
``handle()`` returns as soon as the ack is enqueued.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from hiro_channel_sdk.log_scope_fields import unified_message_text_preview
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger, log_scope

from .comm_log import LOG_IN, comm_extras, comm_peer_label
from .envelope_factory import EnvelopeFactory
from .post_adapt_hooks import EmitOutbound, PostAdaptHook

if TYPE_CHECKING:
    from .message_adapter import MessageAdapterPipeline
    from .server_context import ServerContext

log = Logger.get("MSG_FLOW")


class MessageFlow:
    """Ack + adapt + post-hook chain for ``message_type == "message"``."""

    def __init__(
        self,
        ctx: ServerContext,
        adapter_pipeline: MessageAdapterPipeline | None,
        post_hooks: list[PostAdaptHook],
        emit_outbound: EmitOutbound,
    ) -> None:
        self._ctx = ctx
        self._pipeline = adapter_pipeline
        self._hooks = post_hooks
        self._emit = emit_outbound

    async def handle(self, msg: UnifiedMessage) -> None:
        """Ack immediately, then spawn the adapt-and-dispatch background task."""
        await self._emit(EnvelopeFactory.ack_event(msg))

        asyncio.create_task(
            self._adapt_and_dispatch(msg),
            name=f"adapt-{msg.routing.id}",
        )

        log.fineinfo(
            f"{LOG_IN} Message acked, adapter spawned — {comm_peer_label(msg, self._ctx)}",
            **comm_extras(
                msg,
                channel=msg.routing.channel,
                content_types=[item.content_type for item in msg.content],
            ),
        )

    async def _adapt_and_dispatch(self, msg: UnifiedMessage) -> None:
        """Run the pipeline, then walk every post-adapt hook in order."""
        try:
            if self._pipeline is not None:
                msg = await self._pipeline.process(msg)

            # After STT/description enrichment, widen log_scope ``text_preview`` so post-adapt hooks
            # and downstream logs carry the snippet (device/msg/method stay inherited from inbound scope).
            _post_preview = unified_message_text_preview(msg)
            _adapt_ctx = (
                log_scope(text_preview=_post_preview)
                if _post_preview
                else contextlib.nullcontext()
            )
            with _adapt_ctx:
                for hook in self._hooks:
                    await hook.run(msg, self._emit)
        except Exception as exc:
            log.error(
                f"❌ {LOG_IN} Adapter pipeline failed — {comm_peer_label(msg, self._ctx)}",
                **comm_extras(msg, error=str(exc)),
                exc_info=True,
            )
            await self._emit(
                EnvelopeFactory.routing_error_response(msg, f"Adapter pipeline error: {exc}")
            )
