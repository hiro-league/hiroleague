"""Shared graph helpers extracted from ``base.py``.

Small, pure utilities the chat graph's node groups share (events, tool-call previews). The usage
payload and token estimate are the memory library's (``hiro_memory.replies``), and the retrieval
previews are its knowledge engine's (``hiro_memory.knowledge.previews``).
"""

from __future__ import annotations

import json
from typing import Any

from .events import make_event

IDENTITY_KEYS = ("inbound_id", "chat_channel_id", "character_id")
IDENTITY_PEER_KEYS = ("inbound_id", "chat_channel_id")

# Bounded strings for admin message metadata (separate from ledger previews).
AGENT_TOOL_ARGS_MAX = 2000
AGENT_TOOL_RESULT_MAX = 4000

_MEMORY_TEXT_KEYS = ("memory", "text", "content", "data", "value")


def emit(writer: Any, name: str, payload: dict[str, Any]) -> None:
    """Push a domain event onto the custom stream (consumed by AgentManager)."""
    writer(make_event(name, payload))


def event_identity_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Standard event-payload identity fields (``inbound_id``/``chat_channel_id``/``character_id``)
    pulled from graph state or ``Send`` sub-state.

    Distinct from :func:`hiro_memory.ledger.identity.identity_from_state`, which
    resolves the broader ledger-row identity (``run_id``/``device_id``/``user_id``/``branch_index``
    from envelope + config + ``current_run`` fallback). The two return different shapes; keep the
    names disambiguated — a bare ``identity_from_state`` import is otherwise easy to confuse.
    """
    return {
        "inbound_id": state.get("inbound_id", ""),
        "chat_channel_id": state.get("chat_channel_id", 0),
        "character_id": state.get("character_id", ""),
    }


# Back-compat alias — prefer ``event_identity_from_state`` to avoid colliding with
# ``ledger.identity.identity_from_state``.
identity_from_state = event_identity_from_state


def emit_for(
    writer: Any,
    state: dict[str, Any],
    name: str,
    extra: dict[str, Any] | None = None,
    *,
    identity_keys: tuple[str, ...] = IDENTITY_KEYS,
) -> None:
    """Emit with turn identity merged from ``state`` — avoids repeating ``state.get`` boilerplate."""
    base = event_identity_from_state(state)
    payload = {key: base[key] for key in identity_keys}
    if extra:
        payload.update(extra)
    emit(writer, name, payload)


def _field(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def memory_text(item: Any) -> str:
    """First non-empty memory field in priority order, whitespace-normalized."""
    for key in _MEMORY_TEXT_KEYS:
        value = _field(item, key)
        if value:
            return " ".join(str(value).split())
    return ""


def tool_args_one_line(args: dict[str, Any], *, max_len: int = AGENT_TOOL_ARGS_MAX) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False, default=str, separators=(",", ":"))
    except TypeError:
        text = str(args)
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def tool_result_bounded(content: str, *, max_len: int = AGENT_TOOL_RESULT_MAX) -> str:
    text = str(content or "")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def tool_call_id(call: dict[str, Any]) -> str:
    return str(call.get("id") or "")


def tool_call_name(call: dict[str, Any]) -> str:
    return str(call.get("name") or "")


def tool_call_args(call: dict[str, Any]) -> dict[str, Any]:
    args = call.get("args") or {}
    return args if isinstance(args, dict) else {}
