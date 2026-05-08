"""Media file persistence — saves binary content to disk.

Files are stored at <workspace>/data/media/<channel_id>/<message_pk>.<ext>.
All public functions are synchronous (intended for asyncio.to_thread).
"""

from __future__ import annotations

import base64
from pathlib import Path

from .data_store import media_dir


# Single source of truth for audio MIME → file extension mapping. Used by both
# inbound persistence (message_store.persist_inbound) and outbound TTS
# attachment persistence (agent_manager._synthesize_and_send) so the
# extension shows up the same way regardless of which side produced the bytes.
def audio_extension_for_media_type(media_type: str | None) -> str:
    """Return a stable file extension for an audio MIME type."""
    m = (media_type or "audio/mpeg").lower()
    if "mpeg" in m or "mp3" in m:
        return "mp3"
    if "wav" in m:
        return "wav"
    if "ogg" in m:
        return "ogg"
    if "webm" in m:
        return "webm"
    if "mp4" in m or "m4a" in m:
        return "m4a"
    return "audio"


def save_media_file(
    workspace_path: Path,
    channel_id: int,
    message_pk: int,
    content_bytes: bytes,
    extension: str,
    *,
    slot_index: int = 0,
) -> str:
    """Write bytes to disk and return the relative path (from data/).

    The returned path is suitable for storing in message_attachments.media_path.
    """
    channel_dir = media_dir(workspace_path) / str(channel_id)
    channel_dir.mkdir(parents=True, exist_ok=True)

    stem = str(message_pk) if slot_index == 0 else f"{message_pk}.{slot_index}"
    filename = f"{stem}.{extension.lstrip('.')}"
    file_path = channel_dir / filename
    file_path.write_bytes(content_bytes)

    # Relative to data/ dir so the path stays portable
    return f"media/{channel_id}/{filename}"


def decode_and_save(
    workspace_path: Path,
    channel_id: int,
    message_pk: int,
    base64_body: str,
    extension: str,
    *,
    slot_index: int = 0,
) -> str:
    """Decode a base64 string and save to disk. Returns relative path."""
    content_bytes = base64.b64decode(base64_body)
    return save_media_file(
        workspace_path,
        channel_id,
        message_pk,
        content_bytes,
        extension,
        slot_index=slot_index,
    )
