"""Media file persistence — saves binary content to disk.

Files are stored at <workspace>/data/media/<channel_id>/<message_pk>.<ext>.
All public functions are synchronous (intended for asyncio.to_thread).
"""

from __future__ import annotations

import base64
from pathlib import Path

from .data_store import media_dir


def save_media_file(
    workspace_path: Path,
    channel_id: int,
    message_pk: int,
    content_bytes: bytes,
    extension: str,
) -> str:
    """Write bytes to disk and return the relative path (from data/).

    The returned path is suitable for storing in messages.media_path.
    """
    channel_dir = media_dir(workspace_path) / str(channel_id)
    channel_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{message_pk}.{extension.lstrip('.')}"
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
) -> str:
    """Decode a base64 string and save to disk. Returns relative path."""
    content_bytes = base64.b64decode(base64_body)
    return save_media_file(workspace_path, channel_id, message_pk, content_bytes, extension)
