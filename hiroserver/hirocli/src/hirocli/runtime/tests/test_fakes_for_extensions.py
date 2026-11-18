"""A test environment's stand-ins: with AI or voices set to fake in its switchboard, the core answers an app's ask
itself (services/fakes.py). Nothing reaches a provider, nothing is paid; live (no switchboard) is untouched."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hiro_commons import switchboard

from hirocli.domain.preferences import WorkspacePreferences
from hirocli.runtime import ai_for_extensions as ai
from hirocli.runtime import search_for_extensions as search
from hirocli.runtime import voice_for_extensions as voices
from hirocli.runtime.request_handler import RequestRefused
from hirocli.services import fakes
from hirocli.services.ai_usage.store import hour_start, read_rows


@pytest.fixture
def board(tmp_path, monkeypatch):
    def use(modes: dict[str, str]) -> None:
        path = tmp_path / "switchboard.json"
        path.write_text(json.dumps({"place": "env2", "preset": "Safe", "modes": modes}), encoding="utf-8")
        monkeypatch.setattr(switchboard, "_board", switchboard.read({switchboard.ENV: str(path)}))

    yield use
    monkeypatch.setattr(switchboard, "_board", None)


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch) -> Any:
    """A request from the paired extension "home", in a workspace with no profile and no provider."""

    def nobody(*_a: Any, **_k: Any) -> None:  # a real ask would look for a runner: the stand-in must never
        raise AssertionError("the real AI was reached")

    monkeypatch.setattr(ai, "get_ask_runner", nobody)
    manager = SimpleNamespace(snapshot=lambda: {"x1": {"name": "home"}})
    server = SimpleNamespace(extension_manager=manager, preferences=SimpleNamespace(current=WorkspacePreferences()))
    return SimpleNamespace(workspace_path=tmp_path, msg=SimpleNamespace(routing=SimpleNamespace(sender_id="x1")),
                           server_ctx=server)


def test_a_fake_ask_answers_canned_text_at_no_cost_and_is_counted_as_fake(board, ctx):
    board({"ai": "fake"})
    out = asyncio.run(ai.handle_ai_ask({"use": "ask", "prompt": "Who is home?"}, ctx))
    assert "fake" in out["text"] and "env2" in out["text"]
    assert (out["provider"], out["model"], out["cost"]) == ("fake", "fake", 0.0) and "message" not in out
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    rows = read_rows(ctx.workspace_path, hour_start(now) - timedelta(hours=1), now + timedelta(hours=1))
    assert len(rows) == 1 and rows[0]["source"] == "home" and rows[0]["provider"] == "fake" and rows[0]["cost"] == 0.0
    assert "ask" in rows[0].values()  # filed under the app's use


def test_a_fake_ask_for_json_answers_the_smallest_value_of_that_shape(board, ctx):
    board({"ai": "fake"})
    schema = {"type": "object", "required": ["kind", "sites"], "properties": {
        "kind": {"enum": ["news", "shop"]}, "sites": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"}}}
    out = asyncio.run(ai.handle_ai_ask({"use": "sites", "prompt": "Sort these", "schema": schema}, ctx))
    assert json.loads(out["text"]) == {"kind": "news", "sites": []}


def test_a_fake_conversation_replies_with_no_tool_calls(board, ctx):
    board({"ai": "fake"})
    out = asyncio.run(ai.handle_ai_chat({"use": "agent", "messages": [{"role": "user", "content": "hello"}],
                                         "tools": [{"name": "look", "description": "x", "parameters": {"type": "object"}}]}, ctx))
    assert out["message"]["tool_calls"] == [] and out["message"]["content"] == out["text"]


def test_ai_off_is_still_refused(board, ctx):
    board({"ai": "off"})
    with pytest.raises(RequestRefused, match="AI is off in env2"):
        asyncio.run(ai.handle_ai_ask({"use": "ask", "prompt": "x"}, ctx))


def test_fake_vectors_repeat_per_text_and_ordering_goes_by_shared_words(board, ctx):
    board({"ai": "fake"})
    out = asyncio.run(search.handle_ai_embed({"use": "embedding", "texts": ["the door", "the garden", "the door"]}, ctx))
    assert out["dimensions"] == fakes.DEFAULT_DIMS and len(out["vectors"][0]) == fakes.DEFAULT_DIMS
    assert out["vectors"][0] == out["vectors"][2] != out["vectors"][1]
    assert abs(sum(x * x for x in out["vectors"][0]) - 1) < 1e-6  # a unit vector, as a real model's
    ranked = asyncio.run(search.handle_ai_rerank(
        {"use": "reranking", "query": "front door camera", "documents": ["the garden", "front door", "a door"], "top_n": 2}, ctx))
    assert [r["index"] for r in ranked["results"]] == [1, 2]


def test_a_fake_vector_is_sized_as_the_model_it_stands_in_for():
    assert fakes.dims_of("openai:text-embedding-3-small") == 1536 and fakes.dims_of("BAAI/bge-small-en") == 384
    assert fakes.dims_of("something new") == fakes.DEFAULT_DIMS


def test_a_fake_voice_is_a_real_clip_as_long_as_the_words(board, ctx):
    board({"voices": "fake"})
    out = asyncio.run(voices.handle_voice_speak({"text": "Dinner is ready, everyone come down please.", "use": "speak"}, ctx))
    assert base64.b64decode(out["ogg_b64"])[:4] == b"OggS" and len(base64.b64decode(out["waveform_b64"])) == 64
    assert (out["provider"], out["cost"]) == ("fake", 0.0) and 2.0 < out["seconds"] < 4.0


def test_the_smallest_value_follows_refs_choices_and_limits():
    schema = {"$defs": {"Item": {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer", "minimum": 3}}}},
              "type": "object", "properties": {
                  "items": {"type": "array", "minItems": 2, "items": {"$ref": "#/$defs/Item"}},
                  "maybe": {"anyOf": [{"type": "null"}, {"type": "string"}]}, "on": {"type": "boolean"},
                  "name": {"type": ["string", "null"]}}}
    assert fakes.from_schema(schema) == {"items": [{"n": 3}, {"n": 3}], "maybe": None, "on": False, "name": "fake"}
