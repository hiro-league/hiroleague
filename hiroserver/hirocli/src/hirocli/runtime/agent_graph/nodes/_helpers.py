"""Shared helpers used by multiple node groups."""

from __future__ import annotations

from typing import Any


def _error_slug(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    return "".join(ch for ch in text if ch.isalnum() or ch in {"_", "-", ".", "/"})[:80]


