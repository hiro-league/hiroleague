"""Plain-text and token-usage helpers for model replies, shared by the engine, chat and eval."""

from __future__ import annotations

import math
from typing import Any

from langchain_core.messages import AIMessage


def normalize_reply_content(content: Any) -> str:
    """Convert LangChain/provider message content into Hiro's plain-text body."""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
            continue
        cv = block.get("content")
        if isinstance(cv, str):
            parts.append(cv)
    return "\n".join(p for p in parts if p)



def usage_from_metadata(raw: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = _int_token(raw.get(key))
        if value is not None:
            out[key] = value

    input_details = raw.get("input_token_details")
    if isinstance(input_details, dict):
        cached = _int_token(input_details.get("cache_read"))
        if cached is not None:
            out["cached_input_tokens"] = cached

    output_details = raw.get("output_token_details")
    if isinstance(output_details, dict):
        reasoning = _int_token(output_details.get("reasoning"))
        if reasoning is not None:
            out["reasoning_tokens"] = reasoning

    return out


def llm_usage_payload(
    message: AIMessage,
    *,
    inbound_id: str,
    chat_channel_id: int,
    model_id: str,
    estimated_input_tokens: int,
) -> dict[str, Any]:
    """The usage event payload for one model reply: its token counts, or an estimate when the provider gave none."""
    usage = usage_from_metadata(message.usage_metadata or {})
    payload: dict[str, Any] = {
        "inbound_id": inbound_id,
        "chat_channel_id": chat_channel_id,
        "model_id": model_id,
        "usage_available": bool(usage),
    }
    if usage:
        payload.update(usage)
    else:
        payload["estimated_input_tokens"] = estimated_input_tokens
    return payload


def estimate_text_tokens(text: str) -> int:
    stripped = str(text or "")
    if not stripped:
        return 0
    return max(1, math.ceil(len(stripped) / 4))


def _int_token(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None

