"""Conversation channel thumbnail — 512×512 WebP stored under workspace ``data/channel_photos/``."""

from __future__ import annotations

import io
from pathlib import Path

from hiro_commons.constants.storage import CHANNEL_PHOTOS_DIR
from PIL import Image

from hirocli.domain.character import packaged_default_character_photo_path
from hirocli.domain.data_store import data_dir

CHANNEL_THUMB_FILENAME = "photo_512.webp"
CHANNEL_THUMB_SIZE = 512


def channel_photo_thumb_path(workspace_path: Path, channel_id: int) -> Path:
    return data_dir(workspace_path) / CHANNEL_PHOTOS_DIR / str(channel_id) / CHANNEL_THUMB_FILENAME


def remove_channel_photo_dir(workspace_path: Path, channel_id: int) -> None:
    root = data_dir(workspace_path) / CHANNEL_PHOTOS_DIR / str(channel_id)
    if root.is_dir():
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def resize_image_to_square_webp(src: Path, dest: Path, *, size: int = CHANNEL_THUMB_SIZE) -> None:
    """Read any Pillow-supported image, center-crop to square, resize, write ``.webp``."""
    raw = Path(src).read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(raw)) as im:
        converted = im.convert("RGBA") if im.mode in ("RGBA", "P") else im.convert("RGB")
        w, h = converted.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        cropped = converted.crop((left, top, left + side, top + side))
        out = cropped.resize((size, size), Image.Resampling.LANCZOS)
        rgb = Image.new("RGB", out.size, (255, 255, 255))
        rgb.paste(out, mask=out.split()[3] if out.mode == "RGBA" else None)
        rgb.save(dest, format="WEBP", quality=88, method=6)


def read_channel_thumbnail_bytes(workspace_path: Path, channel_id: int) -> bytes | None:
    """Return PNG/WebP/JPEG bytes for admin preview — workspace thumb or bundled default."""
    thumb = channel_photo_thumb_path(workspace_path, channel_id)
    if thumb.is_file():
        return thumb.read_bytes()
    bundled = packaged_default_character_photo_path()
    if bundled.is_file():
        return bundled.read_bytes()
    return None


def channel_thumbnail_mtimens(workspace_path: Path, channel_id: int) -> int:
    thumb = channel_photo_thumb_path(workspace_path, channel_id)
    if thumb.is_file():
        return int(thumb.stat().st_mtime_ns)
    bundled = packaged_default_character_photo_path()
    if bundled.is_file():
        return int(bundled.stat().st_mtime_ns)
    return 0


def write_channel_thumbnail_from_file(workspace_path: Path, channel_id: int, source_file: Path) -> None:
    """Replace thumbnail from an arbitrary image path (typically a temp uploaded file)."""
    dest = channel_photo_thumb_path(workspace_path, channel_id)
    resize_image_to_square_webp(Path(source_file), dest)


def seed_min_id_channel_thumbnail_if_missing(workspace_path: Path) -> None:
    """On workspace init, stamp the smallest channel id row with ``photo_512.webp``."""
    import sqlite3

    from hirocli.domain.data_store import data_db_path

    db_path = data_db_path(workspace_path)
    if not db_path.is_file():
        return
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute("SELECT MIN(id) FROM channels").fetchone()
        if row is None or row[0] is None:
            return
        min_id = int(row[0])

    thumb = channel_photo_thumb_path(workspace_path, min_id)
    if thumb.is_file():
        return
    src = packaged_default_character_photo_path()
    if src.is_file():
        resize_image_to_square_webp(src, thumb)
