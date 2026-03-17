"""AudioTranscriptionAdapter — bridges TranscriptionService into the adapter pipeline.

Delegates all LangChain/Whisper logic to TranscriptionService. The adapter's
only job is to read item.body and write the transcript into item.metadata.
"""

from __future__ import annotations

from hiro_channel_sdk.models import ContentItem, UnifiedMessage
from hiro_commons.log import Logger

from ...services.transcription_service import TranscriptionService
from ..message_adapter import ContentTypeAdapter

log = Logger.get("ADAPTER.AUDIO")


class AudioTranscriptionAdapter(ContentTypeAdapter):
    """Transcribes audio ContentItems using TranscriptionService."""

    def __init__(self, service: TranscriptionService | None = None) -> None:
        self._service = service or TranscriptionService()

    @property
    def target_content_type(self) -> str:
        return "audio"

    def can_handle(self, msg: UnifiedMessage) -> bool:
        if not self._service.is_available():
            return False
        return super().can_handle(msg)

    async def process_item(self, item: ContentItem) -> str:
        if not item.body:
            raise ValueError("Audio ContentItem has no body to transcribe")
        return await self._service.transcribe(item.body)
