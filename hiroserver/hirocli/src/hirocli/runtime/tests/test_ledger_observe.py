from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.runtime.agent_graph.ledger import (
    current_entry,
    current_substep,
    observe,
    record_child,
    substep_scope,
)
from hirocli.runtime.tests.graph_fakes import RecordingLedgerSink


@pytest.fixture
def sink(tmp_path: Path) -> RecordingLedgerSink:
    return RecordingLedgerSink(tmp_path)


def test_observe_noop_without_active_entry() -> None:
    assert current_entry.get() is None
    observe(decision=("retrieved", "3"), output="x")  # must not raise


_CAP = frozenset({"usage", "decision"})


def test_observe_sets_row_fields(sink: RecordingLedgerSink) -> None:
    entry = sink.open_entry("probe", {}, None, captures=_CAP)
    token = current_entry.set(entry)
    try:
        observe(
            input="in",
            output="out",
            decision=("retrieved", "3"),
            usage={"provider": "p", "model": "m", "input_tokens": 10},
            skipped="skip_code",
        )
        row = entry.to_row()
        assert row["input_preview"] == "in"
        assert row["output_preview"] == "out"
        assert row["decision_kind"] == "retrieved"
        assert row["decision_detail"] == "3"
        assert row["provider"] == "p"
        assert row["model"] == "m"
        assert row["input_tokens"] == 10
        assert row["status"] == "skipped"
        assert row["error_code"] == "skip_code"
    finally:
        current_entry.reset(token)


def test_observe_decision_accepts_bare_string(sink: RecordingLedgerSink) -> None:
    entry = sink.open_entry("probe", {}, None, captures=_CAP)
    token = current_entry.set(entry)
    try:
        observe(decision="ok")
        row = entry.to_row()
        assert row["decision_kind"] == "ok"
        assert row["decision_detail"] == ""
    finally:
        current_entry.reset(token)


def test_observe_fail_applies_defaults(sink: RecordingLedgerSink) -> None:
    entry = sink.open_entry("probe", {}, None, captures=_CAP)
    token = current_entry.set(entry)
    try:
        observe(fail={"code": "provider_down"})
        row = entry.to_row()
        assert row["error_code"] == "provider_down"
        assert row["decision_kind"] == "provider_error"
        assert row["decision_detail"] == "provider_down"
        assert row["output_preview"] == ""
    finally:
        current_entry.reset(token)


def test_observe_error_and_fail(sink: RecordingLedgerSink) -> None:
    entry = sink.open_entry("probe", {}, None, captures=_CAP)
    token = current_entry.set(entry)
    try:
        observe(error="bad_state", fail={"code": "x", "message": "boom", "decision": "failed"})
        row = entry.to_row()
        assert row["status"] == "error"
        assert row["error_code"] == "x"
        assert row["decision_kind"] == "failed"
        assert row["output_preview"] == "error: boom"
    finally:
        current_entry.reset(token)


def test_substep_scope_sets_and_resets(sink: RecordingLedgerSink) -> None:
    entry = sink.open_entry("parent", {}, None)
    token = current_entry.set(entry)
    try:
        assert current_substep.get() is None
        with substep_scope():
            assert current_substep.get() == entry.step_index
        assert current_substep.get() is None
    finally:
        current_entry.reset(token)


def test_substep_scope_noop_without_entry() -> None:
    assert current_entry.get() is None
    with substep_scope():
        assert current_substep.get() is None


def test_substep_scope_resets_on_body_raise(sink: RecordingLedgerSink) -> None:
    entry = sink.open_entry("parent", {}, None)
    token = current_entry.set(entry)
    try:
        with pytest.raises(RuntimeError):
            with substep_scope():
                raise RuntimeError("boom")
        assert current_substep.get() is None
    finally:
        current_entry.reset(token)


def test_record_child_spawns_child_row(sink: RecordingLedgerSink) -> None:
    entry = sink.open_entry("tools", {}, None)
    token = current_entry.set(entry)
    try:
        record_child(
            node="tools/search",
            status="ok",
            elapsed_ms=7,
            branch_index=0,
            input="q: test",
            output="result: ok",
            decision=("ok", "ok"),
        )
        rows = entry.rows(include_parent=False)
        assert len(rows) == 1
        child = rows[0]
        assert child["node"] == "tools/search"
        assert child["status"] == "ok"
        assert child["elapsed_ms"] == 7
        assert child["branch_index"] == 0
        assert child["input_preview"] == "q: test"
        assert child["output_preview"] == "result: ok"
        assert child["decision_kind"] == "ok"
        assert child["step_index"] == entry.step_index
        assert child["sub_step"] == 1
    finally:
        current_entry.reset(token)


def test_record_child_usage_needs_usage_capture(sink: RecordingLedgerSink) -> None:
    """A usage-bearing child (memory/recall_turn) must pass captures={"usage","decision"}, else
    ``to_row`` blanks the model/token columns even after ``add_usage`` — the default child capture is
    decision-only."""
    entry = sink.open_entry("memory_recall", {}, None)
    token = current_entry.set(entry)
    try:
        record_child(
            node="memory/recall_turn",
            captures=("usage", "decision"),
            decision=("search", "2"),
            usage={"provider": "openai", "model": "openai:gpt-5.4", "input_tokens": 800},
        )
        # A search child WITHOUT the usage capture: even if usage is passed, the columns blank out.
        record_child(
            node="memory/search",
            decision=("recalled", "6"),
        )
        turn_row, search_row = entry.rows(include_parent=False)
        assert turn_row["model"] == "openai:gpt-5.4"
        assert turn_row["input_tokens"] == 800
        assert search_row["model"] == ""  # decision-only capture → no usage columns
        assert search_row["decision_kind"] == "recalled"
    finally:
        current_entry.reset(token)


def test_record_child_noop_without_entry() -> None:
    assert current_entry.get() is None
    record_child(node="tools/nope")  # must not raise
