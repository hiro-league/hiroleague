"""A conversation with HiroLeague's AI (llm/profiles.py `chat`, the core's `ai.chat`), against a fake core: what is sent,
the next message as `Chatted` (words or tool calls), the core's refusals as `ask()`'s, and the requests log kept from it."""

import asyncio

import pytest
from hiro_channel_sdk import ExtensionRequestError
from sqlmodel import Session, select

from hiro_extension_kit import testing
from hiro_extension_kit.db import engine
from hiro_extension_kit.errors import Unavailable
from hiro_extension_kit.llm import LLMError, profiles, recorder
from hiro_extension_kit.llm.models import LlmRequest

SEARCH = {"name": "search_memory", "description": "Search the memory graph.",
          "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}
MESSAGES = [{"role": "system", "content": "You find facts in memory."},
            {"role": "user", "content": "Where did Sam travel in May?"}]


def run(coro):
    return asyncio.run(coro)


async def labelled(coro_fn):
    async with recorder.recording("Eval run", "LoCoMo conv-43, question 4"):
        return await coro_fn()


def test_a_tool_call_comes_back_with_what_was_sent(fake_ai):
    fake_ai.answers["ai.chat"] = testing.ai_chat_answer(tool_calls=[{"id": "c1", "name": "search_memory", "args": {"query": "Sam May"}}])

    out = run(labelled(lambda: profiles.chat("retrieval", MESSAGES, tools=[SEARCH])))

    assert fake_ai.asked[-1] == ("ai.chat", {"use": "retrieval", "messages": MESSAGES, "tools": [SEARCH], "label": "LoCoMo conv-43, question 4"})
    assert out.content == "" and out.tool_calls == [{"id": "c1", "name": "search_memory", "args": {"query": "Sam May"}}]
    assert (out.asked.profile_id, out.asked.tokens_in, out.asked.cost) == ("camera", 100, 0.0012)


def test_words_and_a_schema_answer(fake_ai):
    fake_ai.answers["ai.chat"] = testing.ai_chat_answer('{"answer": "Cairo"}')
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}

    out = run(labelled(lambda: profiles.chat("judge", MESSAGES, schema=schema, timeout=30)))

    assert fake_ai.asked[-1] == ("ai.chat", {"use": "judge", "messages": MESSAGES, "schema": schema, "timeout": 30, "label": "LoCoMo conv-43, question 4"})
    assert (out.content, out.tool_calls) == ('{"answer": "Cairo"}', [])


def test_the_conversation_is_kept_in_the_requests_log(fake_ai):
    fake_ai.answers["ai.chat"] = testing.ai_chat_answer("Cairo.")
    run(labelled(lambda: profiles.chat("retrieval", MESSAGES)))
    with Session(engine) as s:
        row = s.exec(select(LlmRequest)).one()
    assert (row.source, row.reply) == ("Eval run", "Cairo.")
    assert row.prompt == "[system]\nYou find facts in memory.\n\n[user]\nWhere did Sam travel in May?"


def test_the_cores_refusals_are_asks(fake_ai):
    fake_ai.answers["ai.chat"] = ExtensionRequestError("no_profile", "none picked")
    with pytest.raises(Unavailable):
        run(profiles.chat("retrieval", MESSAGES))
    fake_ai.answers["ai.chat"] = ExtensionRequestError("failed", "every profile failed")
    with pytest.raises(LLMError):
        run(profiles.chat("retrieval", MESSAGES))
