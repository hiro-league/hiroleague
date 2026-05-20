"""Tests for memory audit log payloads."""

from __future__ import annotations

import json

from hirocli.services.memory.audit_log import (
    build_add_audit,
    build_search_audit,
    log_memory_add,
    log_memory_search,
)


def test_build_search_audit_ranks_and_scores() -> None:
    audit = build_search_audit(
        query="tea?",
        user_id=7,
        character_id="hiro",
        top_k=8,
        threshold=0.1,
        rerank_requested=True,
        rerank_applied=False,
        reranker_enabled=False,
        filters={"user_id": "7", "agent_id": "hiro"},
        results=[
            {"id": "m2", "memory": "likes oolong", "score": 0.42},
            {"id": "m1", "memory": "prefers tea", "score": 0.91},
        ],
        elapsed_ms=33,
    )
    assert audit["operation"] == "search"
    assert audit["params"]["rerank_requested"] is True
    assert audit["params"]["rerank_applied"] is False
    assert audit["results"][0] == {
        "rank": 1,
        "score": 0.42,
        "effective_score": 0.42,
        "id": "m2",
        "memory": "likes oolong",
    }
    assert audit["results"][1]["rank"] == 2


def test_build_search_audit_includes_rerank_score() -> None:
    audit = build_search_audit(
        query="q",
        user_id=1,
        character_id="c",
        top_k=5,
        threshold=0.1,
        rerank_requested=True,
        rerank_applied=True,
        reranker_enabled=True,
        filters={},
        results=[
            {
                "id": "m1",
                "memory": "fact",
                "score": 0.55,
                "rerank_score": 8.12,
            },
        ],
        elapsed_ms=10,
    )
    row = audit["results"][0]
    assert row["score"] == 0.55
    assert row["rerank_score"] == 8.12
    assert row["effective_score"] == 8.12


def test_build_add_audit_includes_usage_and_events() -> None:
    usage = type(
        "U",
        (),
        {
            "provider": "openai",
            "model": "openai:gpt-test",
            "input_tokens": 10,
            "output_tokens": 5,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
            "call_count": 1,
        },
    )()
    audit = build_add_audit(
        user_id=1,
        character_id="hiro",
        run_id="chan-9",
        content="User: hi\nAssistant: hello",
        metadata={"source": "conversation"},
        stored_count=1,
        stored_items=[{"id": "x", "event": "ADD", "memory": "User greeted"}],
        usage=usage,
        elapsed_ms=120,
    )
    assert audit["stored_count"] == 1
    assert audit["usage"]["input_tokens"] == 10
    assert audit["results"][0]["event"] == "ADD"


def test_log_memory_search_emits_audit_json(monkeypatch) -> None:
    calls: list[dict] = []

    class _Log:
        def fineinfo(self, msg: str, *args: object, **kwargs: object) -> None:
            calls.append({"msg": msg, "args": args, "kwargs": kwargs})

    audit = build_search_audit(
        query="q",
        user_id=1,
        character_id="c",
        top_k=5,
        threshold=0.2,
        rerank_requested=False,
        rerank_applied=False,
        reranker_enabled=False,
        filters={},
        results=[],
        elapsed_ms=1,
    )
    log_memory_search(_Log(), audit, user_id=1, character_id="c")
    assert len(calls) == 1
    payload = json.loads(str(calls[0]["kwargs"]["audit_json"]))
    assert payload["operation"] == "search"


def test_log_memory_add_emits_audit_json(monkeypatch) -> None:
    calls: list[dict] = []

    class _Log:
        def fineinfo(self, msg: str, *args: object, **kwargs: object) -> None:
            calls.append({"kwargs": kwargs})

    audit = build_add_audit(
        user_id=2,
        character_id="bot",
        run_id="r1",
        content="turn",
        metadata={},
        stored_count=0,
        stored_items=[],
        usage=None,
        elapsed_ms=5,
    )
    log_memory_add(_Log(), audit, user_id=2, character_id="bot", run_id="r1")
    payload = json.loads(str(calls[0]["kwargs"]["audit_json"]))
    assert payload["operation"] == "add"
