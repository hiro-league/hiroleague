"""Outbound stream chunker — sends ``files.get`` payload as ``MESSAGE_TYPE_STREAM`` frames."""

from __future__ import annotations

import base64
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

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
    label: str = "file",
    log_extras: dict[str, Any] | None = None,
) -> None:
    """Emit stream frames; caller sends ack + terminal JSON responses.

    ``origin_request`` is the inbound ``files.get`` (``request_id`` echoed on each chunk).
    ``label`` is a short human-readable description (e.g. ``"character photo · hiro"``
    or ``"message audio · msg=01HXY…#0"``) used in the single INFO completion line.
    ``log_extras`` adds readable structured fields (media_type, duration_ms, …);
    opaque ids (blob_id, msg_id, device_id) are appended last per the
    Human-first logging rule.
    """
    chunks = list(iter_file_chunks(file_path, chunk_size))
    if not chunks:
        chunks = [b""]
    total = len(chunks)
    size = file_path.stat().st_size
    t0 = time.perf_counter()
    peer = origin_request.routing.sender_id
    extras = dict(log_extras or {})
    log.fineinfo(
        f"⬆️ Stream session opened — {peer} · {label}",
        chunk_count=total,
        size=size,
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
            f"✅ files.get served — {peer} · {label}",
            **extras,
            elapsed_ms=elapsed_ms,
            size=size,
            chunk_count=total,
            blob_id=blob_id,
        )
    except Exception as exc:
        log.warning(
            f"⚠️ files.get aborted — {peer} · {label}",
            blob_id=blob_id,
            error=str(exc),
            exc_info=True,
        )
        raise
