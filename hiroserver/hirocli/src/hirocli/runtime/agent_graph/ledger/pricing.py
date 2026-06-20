"""Cost estimation for ledger node rows."""

from __future__ import annotations

from typing import Any

from hiro_commons.log import Logger

from .helpers import to_float, to_int

log = Logger.get("AGENT.GRAPH")


def price_row(row: dict[str, Any], catalog: Any) -> dict[str, Any]:
    """Attach ``cost_usd`` and ``pricing_version`` to a node row using the model catalog."""
    provider = str(row.get("provider") or "")
    model = str(row.get("model") or "")
    if not model:
        return {**row, "cost_usd": "", "pricing_version": ""}

    try:
        spec = catalog.get_model(model)
        model_kind = spec.model_kind if spec is not None else ""
        if model_kind == "rerank":
            estimate = catalog.estimate_rerank_cost(
                model_id=model,
                processed_tokens=to_int(row.get("input_tokens")),
                search_units=1,
            )
        elif row.get("tts_chars") not in ("", None):
            tts_text_tokens = to_int(row.get("tts_text_tokens")) or to_int(
                row.get("input_tokens")
            )
            estimate = catalog.estimate_tts_usage_cost(
                provider_id=provider,
                model_id=model,
                input_characters=to_int(row.get("tts_chars")),
                input_text_tokens=tts_text_tokens,
                generated_audio_seconds=to_float(row.get("tts_audio_seconds")),
                output_audio_tokens=to_int(row.get("tts_audio_tokens")),
            )
        elif (
            row.get("stt_audio_seconds") not in ("", None)
            or row.get("stt_audio_tokens") not in ("", None)
        ):
            estimate = catalog.estimate_stt_usage_cost(
                provider_id=provider,
                model_id=model,
                audio_seconds=to_float(row.get("stt_audio_seconds")),
                audio_tokens=to_int(row.get("stt_audio_tokens")),
                output_tokens=to_int(row.get("output_tokens")),
            )
        else:
            estimate = catalog.estimate_token_usage_cost(
                model_id=model,
                input_tokens=to_int(row.get("input_tokens")),
                output_tokens=to_int(row.get("output_tokens")),
                cached_input_tokens=to_int(row.get("cached_input_tokens")),
            )
    except Exception as exc:
        log.warning(
            "Graph ledger pricing estimate failed",
            provider=provider,
            model=model,
            error=str(exc),
        )
        return {**row, "cost_usd": "", "pricing_version": ""}

    if not estimate.pricing_available:
        if estimate.reason == "model_not_in_catalog":
            return {**row, "cost_usd": "0", "pricing_version": ""}
        detail = row.get("decision_detail") or estimate.reason or "pricing_missing"
        return {**row, "cost_usd": "", "pricing_version": "", "decision_detail": detail}
    return {
        **row,
        "cost_usd": f"{estimate.estimated_total:.10f}".rstrip("0").rstrip("."),
        "pricing_version": catalog.pricing_version,
    }
