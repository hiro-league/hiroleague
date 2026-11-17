"""Knowledge ingest job ownership tokens for crash recovery."""

from __future__ import annotations

import os
import socket
import uuid

_BOOT_UUID = uuid.uuid4().hex[:8]


def current_owner_token() -> str:
    """Return a token identifying this process boot for ingest job ownership."""
    return f"{socket.gethostname()}:{os.getpid()}:{_BOOT_UUID}"


def is_owner_token_alive(token: str | None) -> bool:
    """Return True when ``token`` refers to a live process on this host."""
    if not token:
        return False
    parts = token.split(":", 2)
    if len(parts) != 3:
        return False
    host, pid_str, _boot = parts
    if host != socket.gethostname():
        # Local workspace files are single-host; treat foreign hosts as not live here.
        return False
    try:
        os.kill(int(pid_str), 0)
    except (OSError, ProcessLookupError, ValueError):
        return False
    return True
