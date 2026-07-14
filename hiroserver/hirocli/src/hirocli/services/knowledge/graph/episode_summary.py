"""Clean a graph episode's body into a readable tooltip for the admin Graph tab's picker.

Conversation-memory episodes are rendered by ``memory.windowing._render_body`` as a windowed
two-speaker transcript — one line per message, ``[YYYY-MM-DD HH:MM] Speaker: text`` (default 3
exchanges = 6 lines). The opaque episode uuid is useless as a label, and the raw body repeats a
``[timestamp]`` on every line. This strips those inline stamps (the picker shows the window's start
time once, in the label) while keeping the ``Speaker: text`` turns and the line breaks, so the
hover tooltip reads like a short chat excerpt. Knowledge (free-text) episodes pass through as-is.

Pure + dependency-free so it stays unit-testable without the graphiti stack.
"""

from __future__ import annotations

import re

# An inline rendered stamp, e.g. "[2026-07-08 09:56] " (seconds optional / defensive).
_STAMP = re.compile(r"\[\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?\]\s*")

_PREVIEW_MAX = 700  # longer body clip used as the option tooltip


def clean_episode_transcript(content: str, *, max_len: int = _PREVIEW_MAX) -> str:
    """Return the episode body with inline ``[timestamp]`` stamps removed, turns + line breaks
    kept, blank lines dropped, and clipped to ``max_len`` chars (``…`` when truncated)."""
    stripped = _STAMP.sub("", content or "")
    cleaned = "\n".join(line.strip() for line in stripped.splitlines() if line.strip())
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip() + "…"
    return cleaned


__all__ = ["clean_episode_transcript"]
