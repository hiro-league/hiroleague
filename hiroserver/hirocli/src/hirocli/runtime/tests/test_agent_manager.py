"""Smoke tests for the slim ``AgentManager`` and reusable helpers.

The TTS attachment behaviour previously tested against
``AgentManager._synthesize_and_send`` now lives inside
``GraphEventSubscriber`` and is exercised end-to-end by integration tests
once the graph runner is wired. Those will be added under
``tests/test_graph_event_subscriber.py`` as the design stabilises.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from hirocli.domain.conversation_channel import CHAT_CHANNEL_ID_METADATA_KEY, create_channel
from hirocli.domain.data_store import data_db_path, ensure_data_db
from hirocli.runtime.agent_graph import GRAPH_RUN_COMPLETED, GRAPH_RUN_FAILED
from hirocli.runtime.agent_graph import ChatAgentGraph
from hirocli.runtime.agent_graph.nodes.conversation import ConversationNodes, _trim_chat_history
from hirocli.runtime.agent_graph.config import ChatGraphConfig
from hirocli.runtime.tests.graph_fakes import ScriptedChatModel, make_agent_services
from hirocli.runtime.agent_manager import (
    AgentManager,
    _audio_extension_for_media_type,
    _reply_content_type,
)


def test_reply_content_type_reports_block_count() -> None:
    assert _reply_content_type([{"type": "text", "text": "Hello"}]) == "list[1]"


def test_audio_extension_for_media_type() -> None:
    assert _audio_extension_for_media_type("audio/mpeg") == "mp3"
    assert _audio_extension_for_media_type("audio/mp3") == "mp3"
    assert _audio_extension_for_media_type("audio/wav") == "wav"
    assert _audio_extension_for_media_type("audio/mp4") == "m4a"


def test_resolve_thread_character_uses_chat_channel_metadata(tmp_path) -> None:
    ensure_data_db(tmp_path)
    import sqlite3

    with sqlite3.connect(str(data_db_path(tmp_path))) as conn:
        uid = int(conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()[0])
    channel = create_channel(tmp_path, name="selected", character_id="agent-a", user_id=uid)
    inbound = UnifiedMessage(
        routing=MessageRouting(
            id="user-msg-selected",
            channel="devices",
            direction="inbound",
            sender_id="u1",
            metadata={CHAT_CHANNEL_ID_METADATA_KEY: f"server-{channel.id}"},
        ),
        content=[ContentItem(content_type="text", body="hello")],
    )

    ctx = SimpleNamespace(workspace_path=tmp_path)
    mgr = AgentManager(ctx, SimpleNamespace(), tts_service=None)

    assert mgr._resolve_thread_character(inbound) == (
        str(channel.id),
        channel.id,
        "agent-a",
        uid,
    )


def test_trim_chat_history_drops_orphaned_tool_exchange_prefix() -> None:
    messages = [
        HumanMessage(content="what is your name and server status?"),
        AIMessage(
            content=[],
            tool_calls=[{"name": "status", "args": {}, "id": "call-status"}],
        ),
        ToolMessage(content="running", tool_call_id="call-status"),
        AIMessage(content=[], tool_calls=[{"name": "character_list", "args": {}, "id": "call-chars"}]),
        ToolMessage(content="Hiro", tool_call_id="call-chars"),
        AIMessage(content="My name is Hiro and the server is running."),
        HumanMessage(content="What is 8 x 7?"),
    ]

    keep = _trim_chat_history(messages, limit=5)

    assert keep == [
        messages[-1],
    ]


def _conv_nodes(tmp_path, **service_kw) -> ConversationNodes:
    services = make_agent_services(tmp_path, **service_kw)
    return ConversationNodes(
        services,
        ChatGraphConfig(
            model=ScriptedChatModel(responses=[]),
            tools=[],
            model_id="fake:model",
            system_prompt=None,
        ),
    )


@pytest.mark.asyncio
async def test_finalize_node_emits_terminal_run_event(tmp_path) -> None:
    graph = _conv_nodes(tmp_path)
    events: list[dict] = []

    await graph.finalize_node(
        {
            "inbound_id": "user-msg-final",
            "chat_channel_id": 42,
            "reply_text": "hello",
            "reply_id": "reply-final",
        },
        events.append,
    )

    assert events == [
        {
            "event": GRAPH_RUN_COMPLETED,
            "payload": {
                "inbound_id": "user-msg-final",
                "chat_channel_id": 42,
                "reply_id": "reply-final",
            },
        }
    ]


@pytest.mark.asyncio
async def test_finalize_node_emits_failed_when_text_reply_missing(tmp_path) -> None:
    graph = _conv_nodes(tmp_path)
    events: list[dict] = []

    await graph.finalize_node(
        {
            "inbound_id": "user-msg-failed",
            "chat_channel_id": 42,
            "reply_text": None,
            "reply_id": None,
        },
        events.append,
    )

    assert events == [
        {
            "event": GRAPH_RUN_FAILED,
            "payload": {
                "inbound_id": "user-msg-failed",
                "chat_channel_id": 42,
                "code": "reply_generation_failed",
                "message": "I couldn't finish generating a reply.",
                "node": "finalize",
            },
        }
    ]
