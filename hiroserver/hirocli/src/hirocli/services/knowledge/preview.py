"""Read workspace files for admin Add-tab preview."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from hirocli.services.knowledge.constants import PREVIEW_MAX_BYTES
from hirocli.services.knowledge.loaders import LoaderRegistry
from hirocli.services.knowledge.preview_formats import resolve_preview_format


@dataclass(frozen=True)
class FilePreviewResult:
    path: str
    relative_path: str
    ext: str
    mime: str | None
    format: str
    supported: bool
    content: str | None
    disabled_reason: str | None
    truncated: bool
    line_count: int
    character_count: int
    estimated_tokens: int


def text_metrics(text: str) -> tuple[int, int, int]:
    if not text:
        return 0, 0, 0
    line_count = text.count("\n") + 1
    character_count = len(text)
    estimated_tokens = max(1, math.ceil(character_count / 4))
    return line_count, character_count, estimated_tokens


def _mime_for_format(preview_format: str) -> str | None:
    if preview_format == "markdown":
        return "text/markdown"
    if preview_format == "plain-text":
        return "text/plain"
    return None


def read_file_preview(path: Path, *, loader_registry: LoaderRegistry) -> FilePreviewResult:
    file_path = path.expanduser().resolve()
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower()
    loader = loader_registry.resolve(ext)
    supported = loader is not None
    preview_format = resolve_preview_format(ext, supported=supported)
    relative_path = file_path.name

    if not supported:
        return FilePreviewResult(
            path=str(file_path),
            relative_path=relative_path,
            ext=ext,
            mime=None,
            format=preview_format,
            supported=False,
            content=None,
            disabled_reason=f"Unsupported extension: {ext or '(none)'}",
            truncated=False,
            line_count=0,
            character_count=0,
            estimated_tokens=0,
        )

    size_bytes = file_path.stat().st_size
    data = file_path.read_bytes()
    truncated = len(data) > PREVIEW_MAX_BYTES
    if truncated:
        data = data[:PREVIEW_MAX_BYTES]

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return FilePreviewResult(
            path=str(file_path),
            relative_path=relative_path,
            ext=ext,
            mime=None,
            format="unsupported",
            supported=False,
            content=None,
            disabled_reason=f"Preview requires UTF-8 text ({exc}).",
            truncated=truncated,
            line_count=0,
            character_count=0,
            estimated_tokens=0,
        )

    line_count, character_count, estimated_tokens = text_metrics(text)
    return FilePreviewResult(
        path=str(file_path),
        relative_path=relative_path,
        ext=ext,
        mime=_mime_for_format(preview_format),
        format=preview_format,
        supported=True,
        content=text,
        disabled_reason=None,
        truncated=truncated or size_bytes > PREVIEW_MAX_BYTES,
        line_count=line_count,
        character_count=character_count,
        estimated_tokens=estimated_tokens,
    )
