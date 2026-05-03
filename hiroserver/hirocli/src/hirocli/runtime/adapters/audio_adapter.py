"""AudioTranscriptionAdapter — bridges STTService into the adapter pipeline.

Delegates all transcription logic to STTService. The adapter's only job is to
read item.body and write the transcript into item.metadata.
"""

from __future__ import annotations

import time
from pathlib import Path

from hiro_channel_sdk.models import ContentItem, UnifiedMessage
from hiro_commons.log import Logger

from ...domain.preferences import load_preferences
from ...services.stt import STTService
from ..message_adapter import ContentTypeAdapter

log = Logger.get("ADAPTER.AUDIO")


class AudioTranscriptionAdapter(ContentTypeAdapter):
    """Transcribes audio ContentItems using STTService."""

    def __init__(
        self,
        workspace_path: Path,
        service: STTService | None = None,
    ) -> None:
        self._workspace_path = workspace_path
        self._service = service or STTService()

    @property
    def target_content_type(self) -> str:
        return "audio"

    def can_handle(self, msg: UnifiedMessage) -> bool:
        # Runtime policy can change while the server is already running, so the adapter
        # checks current preferences for every message instead of caching the startup value.
        if not load_preferences(self._workspace_path).media.input.voice:
            return False
        if not self._service.is_available():
            return False
        return super().can_handle(msg)

    async def process_item(self, item: ContentItem) -> str:
        if not item.body:
            raise ValueError("Audio ContentItem has no body to transcribe")
        source_len = len(item.body)
        mime_type = item.metadata.get("mime_type", "audio/mp4")
        log.info("Transcribing audio", source_len=source_len, mime_type=mime_type)
        _t0 = time.perf_counter()
        transcript = await self._service.transcribe(item.body, mime_type=mime_type)
        _elapsed_ms = int((time.perf_counter() - _t0) * 1000)
        if not transcript.strip():
            log.warning(
                "Transcription returned empty text",
                source_len=source_len,
                elapsed_ms=_elapsed_ms,
            )
        else:
            log.info(
                "Transcription complete",
                transcript_preview=transcript[:150],
                transcript_len=len(transcript),
                elapsed_ms=_elapsed_ms,
            )
        return transcript
