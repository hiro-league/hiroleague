"""Tests for the L3 eval run registry (the live + replay store).

Exercises the event-folding (``_on_event``) and cancellation paths directly so
they don't depend on a live bus loop. The route-level wiring (ensure_subscribed
+ begin_run) is covered by the integration behavior; here we lock the state
machine and the cancel handle.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hirocli.domain.events import DomainEvent
from hirocli.services.knowledge.constants import (
    KNOWLEDGE_EVAL_CANCELLED,
    KNOWLEDGE_EVAL_COMPLETED,
    KNOWLEDGE_EVAL_FAILED,
    KNOWLEDGE_EVAL_QUESTION_COMPLETED,
    KNOWLEDGE_EVAL_SETUP_PROGRESS,
    KNOWLEDGE_EVAL_STARTED,
)
from hirocli.services.knowledge.eval_registry import EvalRunRegistry


def _ev(etype: str, ws: Path, payload: dict) -> DomainEvent:
    return DomainEvent(type=etype, workspace_path=ws, payload=payload)


@pytest.mark.asyncio
async def test_folds_full_run_into_state(tmp_path: Path) -> None:
    reg = EvalRunRegistry()
    fake_task = asyncio.create_task(asyncio.sleep(0))
    reg.begin_run(tmp_path, "rid-1", corpus_source="adam", modes=["flat","graphiti"], task=fake_task)
    await fake_task  # let the no-op task finish; the slot keeps the (done) handle

    await reg._on_event(
        _ev(KNOWLEDGE_EVAL_STARTED, tmp_path, {"run_id": "rid-1", "total_questions": 2, "filters": {"tags": ["t"]}})
    )
    await reg._on_event(
        _ev(KNOWLEDGE_EVAL_SETUP_PROGRESS, tmp_path, {"run_id": "rid-1", "phase": "ingest_adam", "index": 1, "total": 35})
    )
    await reg._on_event(
        _ev(
            KNOWLEDGE_EVAL_QUESTION_COMPLETED,
            tmp_path,
            {"run_id": "rid-1", "index": 0, "total": 2, "id": "q0", "flat": {"answer": "f"}, "graph": {"answer": "g"}},
        )
    )
    await reg._on_event(
        _ev(KNOWLEDGE_EVAL_COMPLETED, tmp_path, {"run_id": "rid-1", "gate": "proceed", "elapsed_ms": 9})
    )

    state = reg.get_run(tmp_path)
    assert state is not None
    assert state.status == "completed"
    assert state.total_questions == 2
    assert len(state.setup_events) == 1
    assert state.rows[0]["graph"]["answer"] == "g"  # full answer kept for replay
    assert state.summary is not None and state.summary["gate"] == "proceed"

    payload = state.to_payload()
    assert "task" not in payload  # not serialized
    assert payload["run_id"] == "rid-1"


@pytest.mark.asyncio
async def test_question_rows_upsert_by_index(tmp_path: Path) -> None:
    reg = EvalRunRegistry()
    t = asyncio.create_task(asyncio.sleep(0))
    reg.begin_run(tmp_path, "rid", corpus_source="adam", modes=["flat","graphiti"], task=t)
    await t
    await reg._on_event(_ev(KNOWLEDGE_EVAL_STARTED, tmp_path, {"run_id": "rid", "total_questions": 1}))
    base = {"run_id": "rid", "index": 0, "total": 1, "flat": {}, "graph": {}}
    await reg._on_event(_ev(KNOWLEDGE_EVAL_QUESTION_COMPLETED, tmp_path, {**base, "id": "first"}))
    await reg._on_event(_ev(KNOWLEDGE_EVAL_QUESTION_COMPLETED, tmp_path, {**base, "id": "dup"}))
    state = reg.get_run(tmp_path)
    assert state is not None
    assert len(state.rows) == 1 and state.rows[0]["id"] == "dup"  # replaced, not appended


@pytest.mark.asyncio
async def test_memory_row_keeps_evidence_recall_live_but_strips_it_on_disk(tmp_path: Path) -> None:
    """Live evidence_recall (LoCoMo) rides the question_completed event for the EV column, so the
    in-memory replay row keeps it — but it must NOT be persisted (the results read recomputes it
    from the sidecar; its `items` carry full episode text we don't want duplicated in row_json)."""
    from hirocli.services.knowledge.eval_store import get_eval_result_store

    reg = EvalRunRegistry()
    t = asyncio.create_task(asyncio.sleep(0))
    reg.begin_run(tmp_path, "rid", corpus_source="loco", modes=["recall"], task=t, track="memory")
    await t
    await reg._on_event(_ev(KNOWLEDGE_EVAL_STARTED, tmp_path, {"run_id": "rid", "track": "memory", "total_questions": 1}))
    ev = {"matched": 1, "total": 1, "items": [{"episode_id": "e1", "text": "big body", "matched": True}]}
    row = {
        "run_id": "rid", "index": 0, "total": 1, "id": "q0", "cost_usd": 0.0,
        "legs": {"recall": {"mode": "recall", "mark": "✓", "recalled": []}},
        "evidence_recall": ev,
    }
    await reg._on_event(_ev(KNOWLEDGE_EVAL_QUESTION_COMPLETED, tmp_path, row))

    state = reg.get_run(tmp_path)
    assert state is not None
    # In-memory replay row carries it (so a mid-run reconnect shows the EV column).
    assert state.rows[0]["evidence_recall"] == ev
    # Persisted row drops it (recomputed on read).
    saved = get_eval_result_store(tmp_path).read_corpus("loco")
    assert "evidence_recall" not in saved["q0"]


@pytest.mark.asyncio
async def test_stale_run_events_ignored(tmp_path: Path) -> None:
    reg = EvalRunRegistry()
    t = asyncio.create_task(asyncio.sleep(0))
    reg.begin_run(tmp_path, "rid-new", corpus_source="adam", modes=["flat","graphiti"], task=t)
    await t
    # Event from a previous run must not mutate the current slot.
    await reg._on_event(_ev(KNOWLEDGE_EVAL_FAILED, tmp_path, {"run_id": "rid-old", "error": "boom"}))
    state = reg.get_run(tmp_path)
    assert state is not None and state.status == "starting" and state.failure_message is None


@pytest.mark.asyncio
async def test_request_cancel_cancels_live_task(tmp_path: Path) -> None:
    reg = EvalRunRegistry()
    task = asyncio.create_task(asyncio.sleep(30))
    reg.begin_run(tmp_path, "rid", corpus_source="adam", modes=["flat","graphiti"], task=task)

    # Wrong run_id → no cancel.
    assert reg.request_cancel(tmp_path, "other") is False
    assert not task.cancelled()

    # Matching run_id → cancel signalled.
    assert reg.request_cancel(tmp_path, "rid") is True
    assert reg.get_run(tmp_path).cancel_requested is True
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancel_after_terminal_is_noop(tmp_path: Path) -> None:
    reg = EvalRunRegistry()
    t = asyncio.create_task(asyncio.sleep(0))
    reg.begin_run(tmp_path, "rid", corpus_source="adam", modes=["flat","graphiti"], task=t)
    await t
    await reg._on_event(_ev(KNOWLEDGE_EVAL_CANCELLED, tmp_path, {"run_id": "rid"}))
    assert reg.get_run(tmp_path).status == "cancelled"
    # No live task to cancel once terminal.
    assert reg.request_cancel(tmp_path, "rid") is False
