"""ai.chat: a conversation whose model may call the extension's tools, on the ask runner's profile walk (the same
profiles, fallbacks and AI usage as ai.ask) — against fake chat models."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from hirocli.domain.preferences import AiPreferences, WorkspacePreferences
from hirocli.services.ai_ask import AskError
from hirocli.services.ai_ask import providers as providers_mod
from hirocli.services.ai_ask import runner as runner_mod
from hirocli.services.ai_ask.params import chat_request_from_params
from hirocli.services.ai_ask.runner import AskRunner
from hirocli.services.ai_usage.store import read_rows

GEMINI = "google:gemini-3.8-flash"
SEARCH = {"name": "search_memory", "description": "Search the memory graph.",
          "parameters": {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}}}}
CONVERSATION = [
    {"role": "system", "content": "You find facts in memory."},
    {"role": "user", "content": "Where did Sam travel in May?"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "search_memory", "args": {"queries": ["Sam May"]}}]},
    {"role": "tool", "content": "Sam visited Cairo in May.", "tool_call_id": "c1"},
]


class FakeStore:
    def is_configured(self, provider_id: str) -> bool:
        return True

    def get(self, provider_id: str) -> None:
        return None


class FakeChat:
    """Just enough of a LangChain chat model: tools bound, structured output, a reply."""

    def __init__(self, reply: AIMessage) -> None:
        self.reply = reply
        self.messages: list[Any] = []
        self.tools: list[Any] = []
        self.schema: Any = None

    def bind_tools(self, tools: list[Any]) -> "FakeChat":
        self.tools = tools
        return self

    def with_structured_output(self, schema: Any, include_raw: bool = False, **kwargs: Any) -> "_Structured":
        self.schema = schema
        return _Structured(self)

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        self.messages = messages
        return self.reply


class _Structured:
    def __init__(self, chat: FakeChat) -> None:
        self.chat = chat

    async def ainvoke(self, messages: list[Any]) -> dict[str, Any]:
        raw = await self.chat.ainvoke(messages)
        return {"raw": raw, "parsed": json.loads(str(raw.content)), "parsing_error": None}


def _reply(content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> AIMessage:
    return AIMessage(content=content, tool_calls=tool_calls or [],
                     usage_metadata={"input_tokens": 300, "output_tokens": 40, "total_tokens": 340})


@pytest.fixture
def chats(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeChat]:
    built: dict[str, FakeChat] = {}
    monkeypatch.setattr(providers_mod, "build_chat_model_from_tuning", lambda model_id, **kwargs: built[model_id])
    monkeypatch.setattr(runner_mod, "_credential_store", lambda path: FakeStore())
    monkeypatch.setattr(providers_mod, "_PLAN_TOOLS", {})  # never the real plan tools
    monkeypatch.setattr(providers_mod, "_DEFAULTS_LOADED", True)
    return built


def _prefs(profiles: dict[str, dict[str, Any]], uses: dict[str, str | None]) -> WorkspacePreferences:
    full = {pid: {"label": pid.title(), **p} for pid, p in profiles.items()}
    return WorkspacePreferences(ai=AiPreferences.model_validate({"profiles": full, "uses": uses}))


def _chat(tmp_path: Path, prefs: WorkspacePreferences, params: dict[str, Any]) -> Any:
    request = chat_request_from_params({"use": "retrieval", **params}, use_key="eval:retrieval", who="eval")
    return asyncio.run(AskRunner(tmp_path).ask(request, prefs=prefs))


def test_a_conversation_is_sent_as_it_was_with_the_tools_and_the_tool_call_comes_back(tmp_path: Path, chats) -> None:
    chats[GEMINI] = FakeChat(_reply(tool_calls=[{"id": "c2", "name": "search_memory", "args": {"queries": ["Cairo trip"]}}]))
    prefs = _prefs({"recall": {"model": GEMINI, "instructions": "Be brief."}}, {"eval:retrieval": "recall"})

    answer = _chat(tmp_path, prefs, {"messages": CONVERSATION, "tools": [SEARCH]})

    sent = chats[GEMINI].messages
    assert [type(m) for m in sent] == [SystemMessage, HumanMessage, AIMessage, ToolMessage]
    assert sent[2].tool_calls[0]["name"] == "search_memory" and sent[3].tool_call_id == "c1"
    # The messages are the whole prompt: the profile's instructions are not added.
    assert all("Be brief." not in str(m.content) for m in sent)
    assert chats[GEMINI].tools == [{"type": "function", "function": SEARCH}]
    assert answer.message == {"content": "", "tool_calls": [{"id": "c2", "name": "search_memory", "args": {"queries": ["Cairo trip"]}}]}
    assert (answer.profile_id, answer.tokens_in, answer.tokens_out) == ("recall", 300, 40)
    assert answer.to_dict()["message"]["tool_calls"][0]["id"] == "c2"
    (row,) = read_rows(tmp_path, datetime.now(UTC) - timedelta(hours=2), datetime.now(UTC) + timedelta(hours=1))  # in AI usage
    assert (row["source"], row["use_id"], row["profile_id"], row["result"], row["tokens_in"]) == ("eval", "retrieval", "recall", "ok", 300)


def test_a_conversation_with_a_schema_answers_its_json(tmp_path: Path, chats) -> None:
    chats[GEMINI] = FakeChat(_reply('{"answer": "Cairo"}'))
    prefs = _prefs({"judge": {"model": GEMINI}}, {"eval:retrieval": "judge"})
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}

    answer = _chat(tmp_path, prefs, {"messages": CONVERSATION[:2], "schema": schema})

    assert json.loads(answer.text) == {"answer": "Cairo"}
    assert json.loads(answer.message["content"]) == {"answer": "Cairo"} and answer.message["tool_calls"] == []
    assert chats[GEMINI].schema["title"] == "answer"  # an untitled schema gets a name, as an ai.ask's


def test_a_plan_profile_is_passed_over_for_its_fallback(tmp_path: Path, chats) -> None:
    chats[GEMINI] = FakeChat(_reply("Cairo."))
    prefs = _prefs({"codex": {"model": "codex:gpt-6.1-sol", "fallback": "api"}, "api": {"model": GEMINI}},
                   {"eval:retrieval": "codex"})

    answer = _chat(tmp_path, prefs, {"messages": CONVERSATION[:2]})

    assert answer.profile_id == "api" and answer.text == "Cairo."
    assert answer.notes == ["Codex: a plan tool can't take a conversation or tools"]


@pytest.mark.parametrize(("params", "said"), [
    ({"messages": []}, "messages"),
    ({"messages": [{"role": "robot", "content": "hi"}]}, "role"),
    ({"messages": [{"role": "tool", "content": "x"}]}, "tool_call_id"),
    ({"messages": CONVERSATION[:2], "tools": [{"name": "x"}]}, "parameters"),
    ({"messages": CONVERSATION[:2], "tools": [SEARCH], "schema": {"type": "object"}}, "not both"),
])
def test_a_malformed_conversation_is_refused_before_anything_is_asked(params: dict[str, Any], said: str) -> None:
    with pytest.raises(AskError) as caught:
        chat_request_from_params({"use": "retrieval", **params}, use_key="eval:retrieval", who="eval")
    assert caught.value.code == "invalid" and said in caught.value.message
