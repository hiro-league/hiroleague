"""Outbound stream chunker — sends ``files.get`` payload as ``MESSAGE_TYPE_STREAM`` frames."""

from __future__ import annotations

import base64
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger

from hirocli.domain.blob_store import DEFAULT_CHUNK_SIZE, iter_file_chunks

from .envelope_factory import EnvelopeFactory

log = Logger.get("STREAM_SEND")
Emit = Callable[[UnifiedMessage], Awaitable[None]]


async def send_file_as_stream(
    *,
    origin_request: UnifiedMessage,
    file_path: Path,
    blob_id: str,
    emit: Emit,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> None:
    """Emit stream frames; caller sends ack + terminal JSON responses.

    ``origin_request`` is the inbound ``files.get`` (``request_id`` echoed on each chunk).
    """
    chunks = list(iter_file_chunks(file_path, chunk_size))
    if not chunks:
        chunks = [b""]
    total = len(chunks)
    t0 = time.perf_counter()
    peer = origin_request.routing.sender_id
    log.info(
        f"⬆️ Stream session opened — {peer} · files.get",
        chunk_count=total,
        size=file_path.stat().st_size,
        blob_id=blob_id,
    )
    try:
        for i, block in enumerate(chunks):
            b64 = base64.b64encode(block).decode("ascii")
            env = EnvelopeFactory.stream_chunk(
                origin_request,
                blob_id=blob_id,
                seq=i,
                final=(i == total - 1),
                body_b64=b64,
            )
            await emit(env)
            log.debug(
                f"⬆️ Stream chunk sent — {peer} · files.get",
                seq=i,
                final=(i == total - 1),
                chunk_bytes=len(block),
                blob_id=blob_id,
            )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            f"✅ Stream session completed — {peer} · files.get",
            chunk_count=total,
            blob_id=blob_id,
            elapsed_ms=elapsed_ms,
        )
    except Exception as exc:
        log.warning(
            f"⚠️ Stream session aborted — {peer} · files.get",
            blob_id=blob_id,
            error=str(exc),
            exc_info=True,
        )
        raise
