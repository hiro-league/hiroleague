"""Shared helpers for GraphState invariant tests (P1c)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from langgraph.checkpoint.memory import InMemorySaver
from typing_extensions import Annotated

from hirocli.domain.data_store import ensure_data_db, get_default_user_id
from hirocli.runtime.agent_graph import ChatAgentGraph, ChatGraphConfig
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.tests.graph_fakes import (
    FakeSTT,
    FakeVision,
    ScriptedChatModel,
    ai_text,
    make_agent_services,
    make_inbound_envelope,
)

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_LARGE_STRING = 1024
_BASE64_LIKE = re.compile(r"^[A-Za-z0-9+/=\s]{1024,}$")


def build_checkpointed_chat(tmp_path: Path) -> tuple[Any, InMemorySaver]:
    ensure_data_db(tmp_path)
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update_many({"memory.enabled": False})
    checkpointer = InMemorySaver()
    services = make_agent_services(
        tmp_path,
        preferences=runtime,
        stt=FakeSTT(text="spoken words"),
        vision=FakeVision(description="a scene"),
        checkpointer=checkpointer,
    )
    compiled = ChatAgentGraph(services).build(
        ChatGraphConfig(
            model=ScriptedChatModel(responses=[ai_text("checkpoint reply")]),
            tools=[],
            model_id="fake:model",
            system_prompt="You are Hiro.",
        )
    )
    return compiled, checkpointer


def turn_state(
    tmp_path: Path,
    envelope: dict[str, Any],
    *,
    inbound_id: str = "in-1",
    messages: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "inbound_id": inbound_id,
        "chat_channel_id": 1,
        "thread_id": "t1",
        "character_id": "hiro",
        "data_user_id": get_default_user_id(tmp_path),
        "model_id": "fake:model",
        "request_voice_reply": False,
        "voice_input_allowed": True,
        "tools_enabled": True,
        "knowledge_enabled": False,
        "inbound_envelope": envelope,
        "routing_metadata": {"source": "test"},
        "messages": list(messages or []),
    }


def media_turn_envelope() -> dict[str, Any]:
    return make_inbound_envelope(audio="AAAA", image="imgdata", text="hello there")


def assert_no_large_bytes(value: Any, *, path: str = "") -> None:
    """Reject raw bytes or oversized base64-ish strings anywhere in the checkpoint tree."""
    if isinstance(value, bytes):
        if len(value) > _LARGE_STRING:
            raise AssertionError(f"large bytes at {path or '<root>'}: {len(value)} bytes")
        return
    if isinstance(value, str):
        if len(value) > _LARGE_STRING and _BASE64_LIKE.match(value.strip()):
            raise AssertionError(f"large base64-like string at {path or '<root>'}: {len(value)} chars")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            assert_no_large_bytes(item, path=next_path)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            next_path = f"{path}[{index}]"
            assert_no_large_bytes(item, path=next_path)


def checkpoint_surface_snapshot(channels: dict[str, Any]) -> dict[str, Any]:
    """Stable checkpoint contract: keys present and scratch fields cleared after a media turn."""
    scratch = {}
    for field in ("audio_items", "image_items", "text_inputs"):
        value = channels.get(field)
        scratch[field] = [] if value is None else value
    return {
        "channel_keys": sorted(channels.keys()),
        "cleared_scratch_fields": scratch,
        "messages_nonempty": bool(channels.get("messages")),
        "transcripts_present": "transcripts" in channels,
        "visions_present": "visions" in channels,
        "errors_present": "errors" in channels,
    }


def load_checkpoint_surface_fixture() -> dict[str, Any]:
    path = _FIXTURES_DIR / "chat_checkpoint_surface.json"
    return json.loads(path.read_text(encoding="utf-8"))


def find_top_level_reducers(state_type: type) -> dict[str, Any]:
    """Return ``field_name -> reducer`` for every ``Annotated[..., reducer]`` on ``state_type``."""
    reducers: dict[str, Any] = {}
    for name, annotation in get_type_hints(state_type, include_extras=True).items():
        if get_origin(annotation) is Annotated:
            args = get_args(annotation)
            if len(args) >= 2:
                reducers[name] = args[1]
    return reducers
