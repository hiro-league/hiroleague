"""Top-level reducer contract for ``GraphState`` (P1c)."""

from __future__ import annotations

import operator
from typing import Any, TypedDict, get_args, get_origin

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated

from hirocli.runtime.agent_graph.state import (
    AudioItem,
    GraphState,
    ImageItem,
    NodeError,
    ReplyAudio,
    SttSend,
    Transcript,
    Vision,
    VisionSend,
    append_or_reset,
)
from hirocli.runtime.tests.state_contract_helpers import find_top_level_reducers

# transcripts/visions/errors use append_or_reset (NOT operator.add): they merge parallel
# Send branches within a turn but reset between turns. Plain operator.add + the durable
# checkpointer accumulated them across turns, leaking stale transcripts into later user_text.
_EXPECTED_REDUCERS = {
    "messages": add_messages,
    "transcripts": append_or_reset,
    "visions": append_or_reset,
    "errors": append_or_reset,
}

# Reducer identities that must never be nested inside a sub-TypedDict (breaks Send merges).
_REDUCER_IDENTITIES = (operator.add, add_messages, append_or_reset)

# Every sub-TypedDict referenced by ``GraphState`` (directly or via ``Send``). Nesting a
# reducer inside any of these breaks parallel ``Send`` merges silently — sweep all of them.
_NESTED_STATE_TYPES = (
    AudioItem,
    ImageItem,
    SttSend,
    VisionSend,
    Transcript,
    Vision,
    NodeError,
    ReplyAudio,
)


def test_graph_state_reducers_are_top_level_only() -> None:
    reducers = find_top_level_reducers(GraphState)
    assert set(reducers) == set(_EXPECTED_REDUCERS)
    assert reducers["messages"] is add_messages
    assert reducers["transcripts"] is append_or_reset
    assert reducers["visions"] is append_or_reset
    assert reducers["errors"] is append_or_reset


@pytest.mark.parametrize("nested", _NESTED_STATE_TYPES)
def test_graph_state_has_no_nested_typed_dict_reducers(nested: type) -> None:
    """Reducer fields must not live inside ANY sub-TypedDict referenced by ``GraphState``."""
    for name, annotation in nested.__annotations__.items():
        if get_origin(annotation) is Annotated:
            args = get_args(annotation)
            if len(args) >= 2 and args[1] in _REDUCER_IDENTITIES:
                pytest.fail(f"nested reducer on {nested.__name__}.{name}")


def test_transcripts_reducer_concatenates_at_runtime() -> None:
    """Schema annotation is necessary but not sufficient — LangGraph must actually invoke
    ``operator.add`` to concatenate partials. Restored from the deleted P6 contract suite so a
    silent reducer-misapplication regression cannot pass purely on annotation-shape checks.
    """
    t1: Transcript = {
        "item_index": 0,
        "transcript": "first",
        "blob_id": None,
        "mime_type": "audio/m4a",
        "duration_ms": None,
    }
    t2: Transcript = {
        "item_index": 1,
        "transcript": "second",
        "blob_id": None,
        "mime_type": "audio/m4a",
        "duration_ms": None,
    }

    def append_a(_state: GraphState) -> dict[str, Any]:
        return {"transcripts": [t1]}

    def append_b(_state: GraphState) -> dict[str, Any]:
        return {"transcripts": [t2]}

    graph = StateGraph(GraphState)
    graph.add_node("a", append_a)
    graph.add_node("b", append_b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)
    result = graph.compile().invoke({})

    transcripts = result.get("transcripts") or []
    assert [tr["transcript"] for tr in transcripts] == ["first", "second"]


def test_scratch_resets_between_turns_with_checkpointer() -> None:
    """Regression guard for the transcript-leak bug: with a durable checkpointer keyed by
    thread_id, ``transcripts`` must NOT accumulate across turns. ``ingest`` emits ``None`` to
    reset; ``append_or_reset`` maps that to ``[]`` so a prior turn's transcripts never leak into
    a later turn. Under the old ``operator.add`` this asserted-away state persisted and leaked.
    """
    from langgraph.checkpoint.memory import MemorySaver

    def ingest(_state: GraphState) -> dict[str, Any]:
        return {"transcripts": None}  # reset the prior turn's checkpointed scratch

    def append_this_turn(state: GraphState) -> dict[str, Any]:
        tr: Transcript = {
            "item_index": 0,
            "transcript": state.get("model_id", ""),  # carry a per-turn marker via a real channel
            "blob_id": None,
            "mime_type": "audio/m4a",
            "duration_ms": None,
        }
        return {"transcripts": [tr]}

    graph = StateGraph(GraphState)
    graph.add_node("ingest", ingest)
    graph.add_node("stt", append_this_turn)
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "stt")
    graph.add_edge("stt", END)
    compiled = graph.compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "t"}}

    r1 = compiled.invoke({"model_id": "turn-1"}, cfg)
    r2 = compiled.invoke({"model_id": "turn-2"}, cfg)

    assert [t["transcript"] for t in r1["transcripts"]] == ["turn-1"]
    # The load-bearing assertion: turn 2 sees ONLY its own transcript, not turn 1's.
    assert [t["transcript"] for t in r2["transcripts"]] == ["turn-2"]


def test_extra_top_level_reducer_would_break_pin() -> None:
    """Negative guard: an extra reducer field must fail the allowed set check."""

    class RogueState(TypedDict):
        messages: Annotated[list[str], add_messages]
        rogue: Annotated[list[str], operator.add]

    found = set(find_top_level_reducers(RogueState))
    assert found - set(_EXPECTED_REDUCERS) == {"rogue"}
    assert found != set(_EXPECTED_REDUCERS)
