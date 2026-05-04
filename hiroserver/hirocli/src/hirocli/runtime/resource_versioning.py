"""Monotonic per-resource version counters for Tier 2 sync reliability."""

from __future__ import annotations

import threading


class ResourceVersionStore:
    """Thread-safe in-memory counters bumped when ``resource.changed`` is emitted."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._versions: dict[str, int] = {}

    def bump(self, resource: str) -> int:
        """Increment and return the new version for ``resource``."""
        with self._lock:
            next_v = self._versions.get(resource, 0) + 1
            self._versions[resource] = next_v
            return next_v

    def get(self, resource: str) -> int:
        """Current version (0 if never bumped)."""
        with self._lock:
            return self._versions.get(resource, 0)
