"""Media processing tools — transcription and image understanding.

These tools expose the same capabilities used by the adapter pipeline,
making them available to the agent, CLI, and HTTP server.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.workspace import WorkspaceError, resolve_workspace
from .base import Tool, ToolParam


def _media_workspace_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


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
            description="STT model to use (optional — defaults to the model configured in preferences)",
            required=False,
        ),
        "workspace": ToolParam(
            str,
            "Workspace name (default: registry default); used for credential store",
            required=False,
        ),
    }

    def execute(self, **kwargs: Any) -> TranscribeResult:
        from ..services.stt import create_stt_service

        source: str = kwargs["source"]
        model: str | None = kwargs.get("model")
        try:
            workspace_path = _media_workspace_path(kwargs.get("workspace"))
        except WorkspaceError as exc:
            raise RuntimeError(str(exc)) from exc
        service = create_stt_service(workspace_path)

        if not service.is_available():
            raise RuntimeError(
                "No STT providers are available for this workspace. "
                "Configure a provider: hiro provider add openai (or google)."
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
        "workspace": ToolParam(
            str,
            "Workspace name (default: registry default); used for credential store",
            required=False,
        ),
    }

    def execute(self, **kwargs: Any) -> DescribeImageResult:
        from ..services.vision_service import VisionService

        source: str = kwargs["source"]
        prompt: str | None = kwargs.get("prompt")
        try:
            workspace_path = _media_workspace_path(kwargs.get("workspace"))
        except WorkspaceError as exc:
            raise RuntimeError(str(exc)) from exc
        service = VisionService(workspace_path=workspace_path)

        if not service.is_available():
            raise RuntimeError(
                "Vision service is not available for this workspace. "
                "Configure the vision model's provider (see IMAGE_VISION_MODEL) via "
                "`hiro provider add`."
            )

        description = service.describe_sync(source, prompt)
        return DescribeImageResult(description=description)
