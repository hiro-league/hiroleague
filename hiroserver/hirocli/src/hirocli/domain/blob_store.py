"""Blob / chunk helpers for file communication (Phase 1: read path only).

Content-addressed blobs use ``sha256:<64 hex>`` ids matching the hex digest
of the file bytes. Large files are split into fixed-size chunks on the wire.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

# Default raw chunk size — matches docs/file-communication-implementation.md §5.5.
DEFAULT_CHUNK_SIZE: int = 49152


def sha256_hex_of_file(path: Path) -> str:
    """Return lowercase hex sha256 of file contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_hex_of_bytes(data: bytes) -> str:
    """Return lowercase hex sha256 of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


def blob_id_for_bytes(data: bytes) -> str:
    """Return canonical blob id ``sha256:<hex>`` for raw bytes."""
    return f"sha256:{sha256_hex_of_bytes(data)}"


def blob_id_for_file(path: Path) -> str:
    """Return canonical blob id for bytes at ``path``."""
    return f"sha256:{sha256_hex_of_file(path)}"


def chunk_count_for_size(size: int, chunk_size: int = DEFAULT_CHUNK_SIZE) -> int:
    """Number of chunks needed for ``size`` bytes (at least 1 when size is 0)."""
    if size <= 0:
        return 1
    return (size + chunk_size - 1) // chunk_size


def iter_file_chunks(path: Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
    """Yield non-empty chunks from ``path`` (final chunk may be smaller)."""
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            yield block
