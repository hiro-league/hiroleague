"""Media processing tools — transcription and image understanding.

These tools expose the same capabilities used by the adapter pipeline,
making them available to the agent, CLI, and HTTP server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import Tool, ToolParam


@dataclass
class TranscribeResult:
    transcript: str

    def __str__(self) -> str:
        return self.transcript


@dataclass
class DescribeImageResult:
    description: str

    def __str__(self) -> str:
        return self.description


class TranscribeTool(Tool):
    """Transcribe an audio file to text.

    Accepts a URL, a ``data:<mime>;base64,...`` data URI, or a raw
    base64-encoded audio string. Optionally specify a model to use.
    """

    name = "transcribe_audio"
    description = (
        "Transcribe an audio file to text. "
        "Provide the audio as a URL, a data URI, or a base64-encoded string. "
        "Optionally specify a model (e.g. 'gpt-4o-transcribe', 'gemini-3.1-flash-lite')."
    )
    params = {
        "source": ToolParam(
            type_=str,
            description="Audio source — URL, data URI, or base64 string",
        ),
        "model": ToolParam(
            type_=str,
            description="STT model to use (optional — defaults to STT_DEFAULT_MODEL or first available)",
            required=False,
        ),
    }

    def execute(self, **kwargs: Any) -> TranscribeResult:
        from ..services.stt import GeminiSTTProvider, OpenAISTTProvider, STTService

        source: str = kwargs["source"]
        model: str | None = kwargs.get("model")
        service = STTService(providers=[OpenAISTTProvider(), GeminiSTTProvider()])

        if not service.is_available():
            raise RuntimeError(
                "No STT providers are available. "
                "Set OPENAI_API_KEY or GOOGLE_API_KEY to enable transcription."
            )

        transcript = service.transcribe_sync(source, model=model) if model else service.transcribe_sync(source)
        return TranscribeResult(transcript=transcript)


class DescribeImageTool(Tool):
    """Describe the contents of an image using a vision model.

    Accepts a URL, a ``data:<mime>;base64,...`` data URI, or a raw
    base64-encoded image string. An optional custom prompt can guide
    the description focus.
    """

    name = "describe_image"
    description = (
        "Describe the visual contents of an image. "
        "Provide the image as a URL, a data URI, or a base64-encoded string. "
        "Optionally provide a custom prompt to guide what to focus on."
    )
    params = {
        "source": ToolParam(
            type_=str,
            description="Image source — URL, data URI, or base64 string",
        ),
        "prompt": ToolParam(
            type_=str,
            description="Custom instruction for the image analysis (optional)",
            required=False,
        ),
    }

    def execute(self, **kwargs: Any) -> DescribeImageResult:
        from ..services.vision_service import VisionService

        source: str = kwargs["source"]
        prompt: str | None = kwargs.get("prompt")
        service = VisionService()

        if not service.is_available():
            raise RuntimeError(
                "Vision service is not available. "
                "Set OPENAI_API_KEY to enable it."
            )

        description = service.describe_sync(source, prompt)
        return DescribeImageResult(description=description)
