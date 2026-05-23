"""Map supported file extensions to admin preview renderers."""

from __future__ import annotations

PREVIEW_FORMAT_BY_EXTENSION: dict[str, str] = {
    ".md": "markdown",
}


def resolve_preview_format(ext: str, *, supported: bool) -> str:
    if not supported:
        return "unsupported"
    return PREVIEW_FORMAT_BY_EXTENSION.get(ext.lower(), "plain-text")
