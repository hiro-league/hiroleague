"""ImageUnderstandingAdapter — bridges VisionService into the adapter pipeline.

Delegates all LangChain/vision logic to VisionService. The adapter's only job
is to read item.body and write the description into item.metadata.
"""

from __future__ import annotations

from hiro_channel_sdk.models import ContentItem, UnifiedMessage
from hiro_commons.log import Logger

from ...services.vision_service import VisionService
from ..message_adapter import ContentTypeAdapter

log = Logger.get("ADAPTER.IMAGE")


class ImageUnderstandingAdapter(ContentTypeAdapter):
    """Describes image ContentItems using VisionService."""

    def __init__(self, service: VisionService | None = None) -> None:
        self._service = service or VisionService()

    @property
    def target_content_type(self) -> str:
        return "image"

    def can_handle(self, msg: UnifiedMessage) -> bool:
        if not self._service.is_available():
            return False
        return super().can_handle(msg)

    async def process_item(self, item: ContentItem) -> str:
        if not item.body:
            raise ValueError("Image ContentItem has no body to analyse")
        return await self._service.describe(item.body)
