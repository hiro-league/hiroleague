"""Process-wide registry for the embedded graph DB: ONE shared resource (the Kuzu
driver) per ``db_path``, reference-counted, plus ONE ``asyncio.Lock`` per ``db_path``
that serializes writers.

Why this exists (docs/kuzu-shared-database-design.md): Kuzu allows only **one
``Database`` object per file**. Before this registry every consumer (eval ingest, graph
ingest, retrieval, the Graph-tab snapshot) opened its **own** ``Database`` on the same
file, so opening the Graph page mid-build threw "Could not set lock on file". The fix is
the canonical Kuzu pattern: **one Database, many Connections** — realized here as one
shared driver handed to every in-process consumer.

Design boundary (G3/G8): this module is **generic** — it imports no ``graphiti``/``kuzu``
internals. Callers pass a ``factory`` (open) and ``closer`` (close), so all graph-engine
knowledge stays in ``graphiti_service.py``. The registry only refcounts an opaque
resource and owns the per-key write lock.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any, Callable

from hiro_commons.log import Logger

log = Logger.get("SVC.KNOWLEDGE.GRAPH.KUZU_REGISTRY")


@dataclass
class _Entry:
    """One shared resource + how many consumers currently hold it."""

    resource: Any
    refcount: int


# Process-wide state, keyed by a stable absolute db_path string.
_REGISTRY: dict[str, _Entry] = {}
# Write locks are kept SEPARATE from _REGISTRY so the lock identity is stable across
# open/close cycles (refcount may hit 0 and reopen; the lock must not be orphaned).
_LOCKS: dict[str, asyncio.Lock] = {}
# Guards mutation of both dicts. Short critical section; the resource I/O (factory/closer)
# is the only slow part and factory runs under the guard intentionally so two first-time
# opens of the same key can't race into two Databases.
_GUARD = threading.Lock()


def acquire(key: str, factory: Callable[[], Any]) -> Any:
    """Return the shared resource for ``key``, opening it via ``factory()`` on first use.

    Increments the refcount; **pair every ``acquire`` with exactly one ``release``**.
    ``factory`` may raise (e.g. an external process holds the file lock) — in that case
    nothing is registered and the exception propagates to the caller.
    """
    with _GUARD:
        entry = _REGISTRY.get(key)
        if entry is None:
            # factory() opens the real file. Kept under the guard so a concurrent
            # first-open of the same key waits rather than opening a 2nd Database.
            resource = factory()
            entry = _Entry(resource=resource, refcount=0)
            _REGISTRY[key] = entry
            log.fineinfo("⬇️ kuzu-registry — opened shared graph resource · key=%s", key)
        entry.refcount += 1
        return entry.resource


def release(key: str, closer: Callable[[Any], None]) -> None:
    """Decrement the refcount for ``key``; when it reaches zero, close the resource via
    ``closer(resource)`` and drop it — which frees the Kuzu file lock.

    ``closer`` runs **outside** the guard (it may do I/O). A missing key is a no-op
    (defensive: double-release shouldn't explode)."""
    resource_to_close: Any = None
    with _GUARD:
        entry = _REGISTRY.get(key)
        if entry is None:
            return
        entry.refcount -= 1
        if entry.refcount <= 0:
            _REGISTRY.pop(key, None)
            resource_to_close = entry.resource
    if resource_to_close is not None:
        try:
            closer(resource_to_close)
        except Exception:
            log.warning("⚠️ kuzu-registry — closer failed · key=%s", key, exc_info=True)
        else:
            log.fineinfo("⬆️ kuzu-registry — closed shared graph resource · key=%s", key)


def write_lock(key: str) -> asyncio.Lock:
    """The per-``key`` writer lock (one ``asyncio.Lock`` per workspace graph).

    All writers (eval ingest, graph ingest, future chat-memory) acquire this SAME lock
    around each ``add_episode`` so writes serialize one-at-a-time — required by both Kuzu
    (single-writer) and graphiti (sequential episode processing for correct dedup).
    Lock identity is stable for the process lifetime regardless of open/close cycles."""
    with _GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _LOCKS[key] = lock
        return lock


# --- Test/introspection helpers (not for production call paths) ---


def _active_keys() -> list[str]:
    """db_path keys with a live shared resource (refcount > 0). Tests assert this
    empties after balanced acquire/release."""
    with _GUARD:
        return list(_REGISTRY.keys())


def _refcount(key: str) -> int:
    with _GUARD:
        entry = _REGISTRY.get(key)
        return entry.refcount if entry else 0


__all__ = ["acquire", "release", "write_lock"]
