"""TranscriptionService — audio-to-text transcription via LangChain Whisper.

Provider: OpenAI Whisper (langchain-community OpenAIWhisperParser).
The service is disabled when OPENAI_API_KEY is not set.

Two interfaces:
  - async transcribe(source)  — for the adapter pipeline and any async caller
  - transcribe_sync(source)   — for tools and other sync callers (runs in a
                                 separate thread so asyncio.run() is safe)
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from hiro_commons.log import Logger

log = Logger.get("SVC.TRANSCRIBE")

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="transcribe")


class TranscriptionService:
    """Transcribes audio from a URL, data URI, or raw base64 string.

    LangChain model resources are lazy-initialised on first use.
    """

    def is_available(self) -> bool:
        """Return True when a supported provider API key is configured."""
        return bool(os.environ.get("OPENAI_API_KEY"))

    async def transcribe(self, source: str) -> str:
        """Transcribe audio and return the transcript text.

        ``source`` may be a URL, a data URI (``data:<mime>;base64,...``),
        or a raw base64-encoded audio string.

        Runs the synchronous Whisper parser in a thread pool so the event
        loop is never blocked during network/IO.
        """
        if not source:
            raise ValueError("Audio source is empty")

        log.info("Transcribing audio")
        audio_bytes = _resolve_audio_bytes(source)

        def _run() -> str:
            from langchain_community.document_loaders.parsers.audio import OpenAIWhisperParser
            from langchain_core.documents.base import Blob

            parser = OpenAIWhisperParser()
            blob = Blob(data=audio_bytes, mimetype="audio/mpeg")
            docs = list(parser.lazy_parse(blob))
            return " ".join(doc.page_content for doc in docs).strip()

        loop = asyncio.get_event_loop()
        transcript = await loop.run_in_executor(_EXECUTOR, _run)
        log.info("Transcription complete", chars=len(transcript))
        return transcript

    def transcribe_sync(self, source: str) -> str:
        """Synchronous wrapper — safe to call from a tool or non-async context.

        Runs the async transcribe() in a dedicated thread so an existing
        event loop in the calling thread is not affected.
        """
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(asyncio.run, self.transcribe(source))
            return future.result()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_audio_bytes(source: str) -> bytes:
    """Convert a source value (data URI, URL, or raw base64) to raw bytes."""
    import base64

    if source.startswith("data:"):
        _header, encoded = source.split(",", 1)
        return base64.b64decode(encoded)
    if source.startswith("http://") or source.startswith("https://"):
        import urllib.request

        with urllib.request.urlopen(source, timeout=30) as resp:  # noqa: S310
            return resp.read()
    return base64.b64decode(source)
