"""Resolve ledger identity fields from graph state, RunnableConfig, and ``current_run``."""

from __future__ import annotations

from typing import Any

from .context import current_run


def resolve_ledger_identity(state: Any, config: Any = None) -> dict[str, Any]:
    """Merge graph state/config with the active ``current_run`` accumulator when needed."""
    identity = identity_from_state(state, config)
    run_id = str(identity.get("run_id") or "").strip()
    if run_id:
        return identity
    parent = current_run.get()
    if parent is None:
        return identity
    merged = dict(identity)
    merged["run_id"] = parent.run_id
    if not str(merged.get("inbound_id") or "").strip():
        merged["inbound_id"] = parent.inbound_id
    if not merged.get("chat_channel_id"):
        merged["chat_channel_id"] = parent.chat_channel_id
    if not str(merged.get("device_id") or "").strip():
        merged["device_id"] = parent.device_id
    if not str(merged.get("user_id") or "").strip():
        merged["user_id"] = parent.user_id
    if not str(merged.get("character_id") or "").strip():
        merged["character_id"] = parent.character_id
    return merged


def identity_from_state(state: Any, config: Any = None) -> dict[str, Any]:
    data = state if isinstance(state, dict) else {}
    envelope = (
        data.get("inbound_envelope")
        if isinstance(data.get("inbound_envelope"), dict)
        else {}
    )
    routing = envelope.get("routing") if isinstance(envelope.get("routing"), dict) else {}
    routing_metadata = (
        routing.get("metadata") if isinstance(routing.get("metadata"), dict) else {}
    )
    state_metadata = (
        data.get("routing_metadata")
        if isinstance(data.get("routing_metadata"), dict)
        else {}
    )
    branch_index = ""
    if isinstance(data.get("audio_item"), dict):
        branch_index = data["audio_item"].get("item_index", "")
    elif isinstance(data.get("image_item"), dict):
        branch_index = data["image_item"].get("item_index", "")

    run_id = ""
    if isinstance(config, dict):
        configurable = config.get("configurable")
        config_metadata = config.get("metadata")
        if isinstance(config_metadata, dict):
            run_id = str(config_metadata.get("ledger_run_id") or "")
        if not run_id and isinstance(configurable, dict):
            run_id = str(configurable.get("run_id") or "")
        if not run_id:
            run_id = str(config.get("run_id") or "")

    return {
        "run_id": run_id,
        "inbound_id": data.get("inbound_id") or routing.get("id") or "",
        "chat_channel_id": data.get("chat_channel_id") or "",
        "device_id": (
            data.get("device_id")
            or routing.get("sender_id")
            or state_metadata.get("device_id")
            or routing_metadata.get("device_id")
            or ""
        ),
        "user_id": (
            data.get("user_id")
            or state_metadata.get("user_id")
            or routing_metadata.get("user_id")
            or ""
        ),
        "character_id": data.get("character_id") or "",
        "branch_index": branch_index,
    }
