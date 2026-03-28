"""Shared formatting helpers (bytes, rates, bounded series) for admin UI."""

from __future__ import annotations

from typing import Any

__all__ = [
    "fmt_bytes",
    "fmt_rate_bps",
    "format_pricing_summary",
    "trim_series_in_place",
]


def fmt_bytes(b: int | float) -> str:
    """Human-readable byte size (B / KB / MB / GB)."""
    if b >= 1024**3:
        return f"{b / (1024**3):.1f} GB"
    if b >= 1024**2:
        return f"{b / (1024**2):.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b:.0f} B"


def fmt_rate_bps(bps: float) -> str:
    """Throughput as N B/s, N KB/s, etc."""
    return f"{fmt_bytes(bps)}/s"


def trim_series_in_place(data: list, limit: int) -> None:
    """Drop oldest points so len(data) <= limit (charts use this for sliding windows)."""
    if len(data) > limit:
        del data[: len(data) - limit]


def format_pricing_summary(
    pricing: dict[str, Any] | None,
    model_kind: str,
    *,
    hosting: str | None = None,
) -> str:
    """One-line catalog pricing for admin tables (LLM catalog design — PricingBlock)."""
    kind = (model_kind or "").strip().lower()
    if pricing is None:
        return "—" if hosting != "local" else "—"

    def _num(key: str) -> float | None:
        v = pricing.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    if kind == "chat":
        inp = _num("input_per_1m_tokens")
        out = _num("output_per_1m_tokens")
        if inp is None and out is None:
            pass
        else:
            parts: list[str] = []
            if inp is not None:
                parts.append(f"${inp:.2f}/1M in")
            if out is not None:
                parts.append(f"${out:.2f}/1M out")
            return " · ".join(parts)

    if kind == "embedding":
        inp = _num("input_per_1m_tokens")
        if inp is not None:
            return f"${inp:.2f}/1M tokens"

    if kind == "tts":
        pc = _num("per_character")
        if pc is not None:
            per_1k = pc * 1000.0
            return f"${per_1k:.4f}/1K chars"

    if kind == "stt":
        ps = _num("per_second")
        if ps is not None:
            return f"${ps:.4f}/sec audio"

    if kind == "image_gen":
        pi = _num("per_image")
        if pi is not None:
            return f"${pi:.4f}/image"

    # Any remaining priced field
    for key, suffix in (
        ("input_per_1m_tokens", "/1M in"),
        ("output_per_1m_tokens", "/1M out"),
        ("per_character", " / char"),
        ("per_second", "/sec"),
        ("per_image", "/image"),
    ):
        n = _num(key)
        if n is not None:
            return f"${n:.4f}{suffix}"

    return "—"
