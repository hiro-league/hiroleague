"""Shared helpers for extracting per-modality token counts from provider usage payloads.

Centralizes the parsing of provider-specific ``usage_metadata`` shapes (Gemini
``usageMetadata.promptTokensDetails`` / ``candidatesTokensDetails`` rows with
modality-tagged token counts, plus the aggregate-counter fallbacks) so callers
on both sides of the graph — the ``GraphEventSubscriber`` (run-level cost) and
the ``LedgerSink`` (per-node pricing) — agree on the same numbers from the same
upstream payload.

Pure parsing helpers; no I/O, no logging, no project-specific dependencies.
"""

from __future__ import annotations

import numbers
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "gemini_usage_aggregate_fallback",
    "modality_token_count",
    "coerce_positive_int",
]


def coerce_positive_int(token_raw: Any) -> int | None:
    """Parse token counters from protobuf / pydantic / google-genai shapes."""
    if token_raw is None:
        return None
    if isinstance(token_raw, bool):
        return None
    if isinstance(token_raw, numbers.Integral):
        return int(token_raw)
    if isinstance(token_raw, float) and token_raw.is_integer():
        return int(token_raw)
    if isinstance(token_raw, str):
        try:
            return int(token_raw.strip())
        except ValueError:
            return None
    nested = getattr(token_raw, "value", None)
    if nested is not None and nested is not token_raw:
        return coerce_positive_int(nested)
    try:
        return int(token_raw)
    except (TypeError, ValueError):
        return None


def modality_token_count(
    usage_metadata: Mapping[str, Any] | None,
    *,
    detail_keys: tuple[str, ...],
    modality: str,
) -> int:
    """Sum ``tokenCount`` over rows in ``detail_keys`` whose ``modality`` matches.

    ``detail_keys`` is provided in priority order; the first key that yields a
    non-empty list wins. Each row may be a Mapping or a pydantic / proto model
    (``model_dump`` is consulted). Modality labels are normalized (case, trailing
    enum-prefix segments) before comparison.
    """
    if usage_metadata is None:
        return 0
    expected = _modality_label(modality)
    for key in detail_keys:
        rows = _usage_detail_rows(usage_metadata.get(key))
        if not rows:
            continue
        total = 0
        for item in rows:
            mapping = _usage_row_mapping(item)
            raw_mod = mapping.get("modality") or mapping.get("modalityType")
            item_modality = _modality_label(raw_mod)
            if item_modality != expected:
                continue
            raw_tc = mapping.get("tokenCount")
            if raw_tc is None:
                raw_tc = mapping.get("token_count")
            n = coerce_positive_int(raw_tc)
            if n is not None:
                total += n
        if total > 0:
            return total
    return 0


def gemini_usage_aggregate_fallback(
    usage_metadata: Mapping[str, Any] | None,
    *,
    input_text_tokens: int,
    output_audio_tokens: int,
) -> tuple[int, int]:
    """When per-modality rows fail to parse, fall back to top-level aggregate counters.

    Uses ``promptTokenCount`` / ``candidatesTokenCount`` (or their snake_case aliases)
    only when the corresponding modality-derived value is non-positive.
    """
    text_out = input_text_tokens
    audio_out = output_audio_tokens
    if usage_metadata is None:
        return text_out, audio_out
    if text_out <= 0:
        v = coerce_positive_int(usage_metadata.get("promptTokenCount"))
        if v is None:
            v = coerce_positive_int(usage_metadata.get("prompt_token_count"))
        if v is not None:
            text_out = v
    if audio_out <= 0:
        v = coerce_positive_int(usage_metadata.get("candidatesTokenCount"))
        if v is None:
            v = coerce_positive_int(usage_metadata.get("candidates_token_count"))
        if v is not None:
            audio_out = v
    return text_out, audio_out


def _usage_detail_rows(details: Any) -> list[Any]:
    """Normalize Gemini usage ``*Details`` fields (list, tuple, protobuf repeated, …)."""
    if details is None:
        return []
    if isinstance(details, (str, bytes, dict)):
        return []
    if isinstance(details, list):
        return details
    if isinstance(details, Sequence):
        try:
            return list(details)
        except Exception:
            return []
    try:
        return list(details)
    except TypeError:
        return []


def _usage_row_mapping(item: Any) -> Mapping[str, Any]:
    if isinstance(item, Mapping):
        return item
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(by_alias=True, exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    return {}


def _modality_label(raw: Any) -> str:
    if raw is None:
        return ""
    val = getattr(raw, "value", raw)
    if isinstance(val, bytes):
        try:
            val = val.decode("ascii")
        except Exception:
            val = str(val)
    label = str(val).strip().upper()
    if "." in label:
        label = label.rsplit(".", 1)[-1]
    return label
