"""Round-trip tests for ``ledger.identity`` resolution."""

from __future__ import annotations

from hirocli.runtime.agent_graph.ledger import RunAccumulator
from hirocli.runtime.agent_graph.ledger.context import current_run
from hirocli.runtime.agent_graph.ledger.identity import identity_from_state, resolve_ledger_identity


def test_chat_state_identity_from_envelope() -> None:
    state = {
        "inbound_id": "in-42",
        "chat_channel_id": 9,
        "character_id": "hiro",
        "routing_metadata": {"device_id": "dev-1", "user_id": "user-1"},
        "inbound_envelope": {
            "routing": {
                "id": "env-in",
                "sender_id": "sender-1",
                "metadata": {"device_id": "meta-dev", "user_id": "meta-user"},
            }
        },
        "audio_item": {"item_index": 2},
    }
    identity = identity_from_state(state, {"configurable": {"run_id": "run-chat-1"}})
    assert identity == {
        "run_id": "run-chat-1",
        "inbound_id": "in-42",
        "chat_channel_id": 9,
        "device_id": "sender-1",
        "user_id": "user-1",
        "character_id": "hiro",
        "branch_index": 2,
    }


def test_knowledge_standalone_falls_back_to_current_run() -> None:
    parent = RunAccumulator(
        sink=object(),  # type: ignore[arg-type]
        run_id="eval-k-1",
        inbound_id="k-in",
        chat_channel_id=0,
        device_id="dev-k",
        user_id="user-k",
        character_id="hiro",
    )
    token = current_run.set(parent)
    try:
        identity = resolve_ledger_identity({"query": "what?"}, None)
        assert identity["run_id"] == "eval-k-1"
        assert identity["inbound_id"] == "k-in"
        assert identity["device_id"] == "dev-k"
        assert identity["user_id"] == "user-k"
        assert identity["character_id"] == "hiro"
    finally:
        current_run.reset(token)


def test_nested_knowledge_inherits_parent_run_without_overwriting_state() -> None:
    parent = RunAccumulator(
        sink=object(),  # type: ignore[arg-type]
        run_id="chat-in-1",
        inbound_id="in-1",
        chat_channel_id=3,
        character_id="hiro",
    )
    token = current_run.set(parent)
    try:
        identity = resolve_ledger_identity(
            {
                "inbound_id": "in-1",
                "chat_channel_id": 3,
                "character_id": "hiro",
                "knowledge_query": "what is hiro?",
            },
            None,
        )
        assert identity["run_id"] == "chat-in-1"
        assert identity["inbound_id"] == "in-1"
    finally:
        current_run.reset(token)
