"""Shared pure helpers for ledger row shaping."""

from __future__ import annotations

from typing import Any


def slug(value: str) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_")
    return "".join(ch for ch in raw if ch.isalnum() or ch in {"_", "-", ".", "/"})[:80]


def preview(value: str, *, max_len: int = 280) -> str:
    compact = " ".join(str(value or "").split())
    return compact[: max(0, max_len)]


def blank_none(value: Any) -> Any:
    return "" if value is None else value


def blank_zero_float(value: float) -> float | str:
    return "" if value <= 0 else value


def format_cost(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".")


def row_kind(row: dict[str, Any]) -> str:
    return str(row.get("row_kind") or "node")


def to_int(value: Any) -> int:
    try:
        if value in ("", None):
            return 0
        return max(0, int(value))
    except Exception:
        return 0


def to_float(value: Any) -> float:
    try:
        if value in ("", None):
            return 0.0
        return max(0.0, float(value))
    except Exception:
        return 0.0
