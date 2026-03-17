"""MessageAdapterPipeline — content enrichment before agent queue.

Adapters run concurrently within a single message (audio and image processing
are independent). Each adapter writes its output into ContentItem.metadata
in-place. The original body is always preserved.

Enrichment contract:
  - On success: item.metadata["description"] = "<enriched text>"
  - On error:   item.metadata["adapter_error"] = "<error description>"
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from hiro_channel_sdk.models import ContentItem, UnifiedMessage


class MessageAdapter(ABC):
    """Minimal interface for all message adapters."""

    @abstractmethod
    def can_handle(self, msg: UnifiedMessage) -> bool:
        """Return True if this adapter has work to do on the given message."""

    @abstractmethod
    async def adapt(self, msg: UnifiedMessage) -> UnifiedMessage:
        """Enrich the message in-place and return it."""


class ContentTypeAdapter(MessageAdapter):
    """Template Method base for adapters that target a specific content_type.

    Handles content_type matching, item iteration, error capture, and writing
    results into item.metadata["description"]. Subclasses only implement:
      - target_content_type (property)
      - process_item(item) -> str
    """

    @property
    @abstractmethod
    def target_content_type(self) -> str:
        """The content_type string this adapter processes (e.g. "audio")."""

    @abstractmethod
    async def process_item(self, item: ContentItem) -> str:
        """Process a single matching ContentItem and return the enriched text."""

    def can_handle(self, msg: UnifiedMessage) -> bool:
        return any(i.content_type == self.target_content_type for i in msg.content)

    async def adapt(self, msg: UnifiedMessage) -> UnifiedMessage:
        for item in msg.content:
            if item.content_type == self.target_content_type:
                try:
                    item.metadata["description"] = await self.process_item(item)
                except Exception as exc:
                    item.metadata["adapter_error"] = str(exc)
        return msg


class MessageAdapterPipeline:
    """Runs applicable adapters concurrently on a message.

    Independent adapters (e.g. audio and image) run via asyncio.gather so
    a message with both audio and image content is enriched in parallel.
    Each adapter touches only its own content_type, so concurrent mutation
    of different items in msg.content is conflict-free.
    """

    def __init__(self, adapters: list[MessageAdapter] | None = None) -> None:
        self._adapters: list[MessageAdapter] = adapters or []

    async def process(self, msg: UnifiedMessage) -> UnifiedMessage:
        applicable = [a for a in self._adapters if a.can_handle(msg)]
        if not applicable:
            return msg
        await asyncio.gather(*(a.adapt(msg) for a in applicable))
        return msg
