from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import Any

import pytest

from hiro_commons.log import Logger
from hirocli.runtime.agent_graph.base import BaseAgentGraph
from hirocli.runtime.agent_graph.ledger import (
    LedgerSink,
    RunAccumulator,
    current_entry,
    current_run,
    current_substep,
    graph_logged,
)


class LedgerProbeGraph(BaseAgentGraph):
    def build(self, **_: Any):
        raise NotImplementedError

    @graph_logged()
    async def ok_node(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    @graph_logged()
    async def early_node(self, state: dict[str, Any]) -> dict[str, Any]:
        return {}

    @graph_logged()
    async def error_node(self, state: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("boom")

    @graph_logged()
    async def cancelled_node(self, state: dict[str, Any]) -> dict[str, Any]:
        raise asyncio.CancelledError()

    @graph_logged(flush=False)
    async def child_node(self, state: dict[str, Any]) -> dict[str, Any]:
        entry = current_entry.get()
        assert entry is not None
        child = entry.spawn_child(node="tools/search", elapsed_ms=7)
        child.add_usage(provider="openai", model="openai:gpt-5.4", input_tokens=10)
        child.set_decision("ok", "ok")
        return {}

    @graph_logged()
    async def timing_only_node(self, state: dict[str, Any]) -> dict[str, Any]:
        entry = current_entry.get()
        assert entry is not None
        entry.add_usage(provider="openai", model="openai:gpt-5.4", input_tokens=10)
        entry.set_decision("text_reply", "ok")
        return {}

    @graph_logged(captures={"usage", "decision"})
    async def call_model_node(self, state: dict[str, Any]) -> dict[str, Any]:
        entry = current_entry.get()
        assert entry is not None
        entry.add_usage(
            provider="openai",
            model="openai:gpt-5.4",
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=10,
            reasoning_tokens=3,
        )
        entry.set_decision("text_reply", "ok")
        return {}


@pytest.fixture(autouse=True)
def _setup_logger() -> None:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


@pytest.mark.asyncio
async def test_ledger_wrapper_writes_ok_and_resets_context(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.ok_node(_state("in-ok"))

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "chat-in-ok"
    assert rows[0]["node"] == "ok"
    assert rows[0]["status"] == "ok"
    assert current_entry.get() is None


@pytest.mark.asyncio
async def test_ledger_wrapper_writes_error_cancelled_and_early_return(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.early_node(_state("in-early"))
    with pytest.raises(ValueError):
        await graph.error_node(_state("in-error"))
    with pytest.raises(asyncio.CancelledError):
        await graph.cancelled_node(_state("in-cancel"))

    rows = _rows(tmp_path)
    by_node = {row["node"]: row for row in rows}
    assert by_node["early"]["status"] == "ok"
    assert by_node["error"]["status"] == "error"
    assert by_node["error"]["error_code"] == "value"
    assert by_node["cancelled"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_ledger_spawn_child_writes_sibling_row_without_parent(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.child_node(_state("in-child"))

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["node"] == "tools/search"
    assert rows[0]["run_id"] == "chat-in-child"
    assert rows[0]["decision_kind"] == "ok"
    assert rows[0]["model"] == ""
    assert rows[0]["input_tokens"] == ""
    # Spawned tool rows nest under their parent step (1) as sub-steps rather than consuming a step.
    assert rows[0]["step_index"] == "1"
    assert rows[0]["sub_step"] == "1"


@pytest.mark.asyncio
async def test_open_entry_numbers_subgraph_rows_as_substeps(tmp_path: Path) -> None:
    """A parent node that sets ``current_substep`` makes nested rows number as ``N.1``, ``N.2`` …"""
    graph = _graph(tmp_path)
    sink = graph._ledger_sink

    parent = sink.open_entry("knowledge_retrieve", _state("in-sub"))
    assert parent.step_index == 1
    assert parent.sub_step == ""

    token = current_substep.set(parent.step_index)
    try:
        first = sink.open_entry("knowledge/parse_query", _state("in-sub"))
        second = sink.open_entry("knowledge/embed_query", _state("in-sub"))
    finally:
        current_substep.reset(token)

    assert (first.step_index, first.sub_step) == (1, 1)
    assert (second.step_index, second.sub_step) == (1, 2)

    # Top-level numbering resumes after the substep scope closes (parallel branch, next chat node).
    after = sink.open_entry("memory_search", _state("in-sub"))
    assert after.step_index == 2
    assert after.sub_step == ""


@pytest.mark.asyncio
async def test_ledger_tracks_node_attempts_and_honors_captures(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.ok_node(_state("in-attempt"))
    await graph.ok_node(_state("in-attempt"))
    await graph.timing_only_node(_state("in-captures"))

    rows = _rows(tmp_path)
    ok_rows = [row for row in rows if row["node"] == "ok"]
    assert [row["node_attempt"] for row in ok_rows] == ["1", "2"]
    timing_row = [row for row in rows if row["node"] == "timing_only"][0]
    assert timing_row["model"] == ""
    assert timing_row["input_tokens"] == ""
    assert timing_row["decision_kind"] == ""


@pytest.mark.asyncio
async def test_ledger_tracking_is_bounded_per_sink(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    graph._ledger_sink._max_tracked_runs = 2

    await graph.ok_node(_state("in-one"))
    await graph.ok_node(_state("in-two"))
    await graph.ok_node(_state("in-three"))

    assert list(graph._ledger_sink._step_indexes) == ["chat-in-two", "chat-in-three"]
    assert len(graph._ledger_sink._attempt_indexes) == 2


@pytest.mark.asyncio
async def test_send_branch_identity_and_caught_error_status(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.stt_node(
        {
            "audio_item": {"item_index": 3, "body": "", "mime_type": "audio/m4a"},
            "inbound_id": "in-send",
            "chat_channel_id": 7,
            "character_id": "hiro",
            "routing_metadata": {"device_id": "dev-1", "user_id": "user-1"},
        },
        lambda _event: None,
    )

    row = _rows(tmp_path)[0]
    assert row["status"] == "error"
    assert row["branch_index"] == "3"
    assert row["character_id"] == "hiro"
    assert row["device_id"] == "dev-1"
    assert row["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_skipped_node_preserves_skipped_status(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    await graph.tts_node(
        {
            "inbound_id": "in-tts-skip",
            "chat_channel_id": 7,
            "reply_text": "",
            "character_id": "hiro",
        },
        lambda _event: None,
    )

    row = _rows(tmp_path)[0]
    assert row["node"] == "tts"
    assert row["status"] == "skipped"
    assert row["decision_kind"] == "skipped_no_text"


def _graph(tmp_path: Path) -> LedgerProbeGraph:
    return LedgerProbeGraph(
        workspace_path=tmp_path,
        stt_service=None,
        vision_service=None,
        tts_service=None,
        credential_store=None,
        checkpointer=None,
    )


def test_stt_usage_does_not_get_token_priced(tmp_path: Path) -> None:
    graph = _graph(tmp_path)

    priced = graph._ledger_sink._with_cost(
        {
            "provider": "openai",
            "model": "openai:gpt-4o-transcribe",
            "stt_audio_seconds": 12.5,
        }
    )

    assert priced["cost_usd"] == ""
    assert priced["pricing_version"] == ""


def test_tts_audio_seconds_are_persisted(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    entry = graph._ledger_sink.open_entry(
        "tts",
        _state("in-tts"),
        captures=frozenset({"usage"}),
    )
    entry.add_usage(
        provider="openai",
        model="openai:gpt-4o-mini-tts",
        input_tokens=5,
        tts_chars=25,
        tts_audio_seconds=2.5,
    )

    graph._ledger_sink.write_rows(entry.rows(include_parent=True))

    row = _rows(tmp_path)[0]
    assert row["tts_audio_seconds"] == "2.5"


def test_node_previews_are_persisted_and_capped(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    entry = graph._ledger_sink.open_entry(
        "memory_search",
        _state("in-preview"),
        captures=frozenset({"decision"}),
    )
    entry.set_input_preview("search: " + ("hello " * 80))
    entry.set_output_preview("results: 2; " + ("memory " * 80))

    graph._ledger_sink.write_rows(entry.rows(include_parent=True))

    row = _rows(tmp_path)[0]
    assert row["input_preview"].startswith("search: hello")
    assert row["output_preview"].startswith("results: 2; memory")
    assert len(row["input_preview"]) == 280
    assert len(row["output_preview"]) == 280


def test_gemini_tts_prices_with_audio_tokens(tmp_path: Path) -> None:
    """Gemini TTS rows must be priced once ``tts_text_tokens`` and ``tts_audio_tokens`` land.

    Reproduces the cost-of-zero gap: the catalog's Google TTS branch needs both
    modality token counts; without them every row was unpriced.
    """
    graph = _graph(tmp_path)

    priced = graph._ledger_sink._with_cost(
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash-preview-tts",
            "tts_chars": 80,
            "tts_text_tokens": 18,
            "tts_audio_tokens": 240,
            "tts_audio_seconds": 4.0,
            "input_tokens": 18,
        }
    )

    assert priced["cost_usd"] not in ("", None)
    assert float(priced["cost_usd"]) > 0
    assert priced["pricing_version"]


def test_gemini_tts_without_audio_tokens_stays_unpriced(tmp_path: Path) -> None:
    """Missing AUDIO modality tokens (e.g. older usage_metadata shapes) still no-price."""
    graph = _graph(tmp_path)

    priced = graph._ledger_sink._with_cost(
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash-preview-tts",
            "tts_chars": 80,
            "tts_text_tokens": 18,
            "tts_audio_seconds": 4.0,
            "input_tokens": 18,
        }
    )

    assert priced["cost_usd"] == ""
    assert priced["pricing_version"] == ""


@pytest.mark.asyncio
async def test_run_accumulator_writes_aggregate_and_evicts_run(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    acc = RunAccumulator(
        sink=graph._ledger_sink,
        run_id="chat-in-run",
        inbound_id="in-run",
        chat_channel_id=5,
        device_id="dev-1",
        user_id="user-1",
        character_id="hiro",
    )
    token = current_run.set(acc)
    try:
        await graph.call_model_node(_state("in-run"))
        graph._ledger_sink.write_run_row(
            acc,
            status="completed",
            decision_kind="completed",
            decision_detail="text_reply",
            input_preview="hello " * 80,
            output_preview="world " * 80,
        )
        graph._ledger_sink.evict_run(acc.run_id)
    finally:
        current_run.reset(token)

    rows = _rows(tmp_path)
    node_row = [row for row in rows if row["row_kind"] == "node"][0]
    run_row = [row for row in rows if row["row_kind"] == "run"][0]
    assert run_row["node"] == "@run"
    assert run_row["step_index"] == ""
    assert run_row["status"] == "completed"
    assert run_row["input_tokens"] == "100"
    assert run_row["output_tokens"] == "20"
    assert run_row["cached_input_tokens"] == "10"
    assert run_row["reasoning_tokens"] == "3"
    assert run_row["model"] == "openai:gpt-5.4"
    assert run_row["cost_usd"] == node_row["cost_usd"]
    assert len(run_row["input_preview"]) == 280
    assert len(run_row["output_preview"]) == 280
    assert "chat-in-run" not in graph._ledger_sink._step_indexes
    assert not graph._ledger_sink._attempt_indexes


@pytest.mark.parametrize(
    ("status", "error_code"),
    [("failed", "provider_error"), ("cancelled", "cancelled")],
)
def test_run_row_records_terminal_failure_statuses(
    tmp_path: Path,
    status: str,
    error_code: str,
) -> None:
    graph = _graph(tmp_path)
    acc = RunAccumulator(
        sink=graph._ledger_sink,
        run_id=f"chat-{status}",
        inbound_id=status,
        chat_channel_id=5,
    )

    graph._ledger_sink.write_run_row(
        acc,
        status=status,
        error_code=error_code,
        decision_kind=status,
        decision_detail=error_code,
    )

    row = _rows(tmp_path)[0]
    assert row["row_kind"] == "run"
    assert row["status"] == status
    assert row["error_code"] == error_code


def _state(inbound_id: str) -> dict[str, Any]:
    return {
        "inbound_id": inbound_id,
        "chat_channel_id": 5,
        "character_id": "hiro",
        "model_id": "openai:gpt-5.4",
    }


def _rows(tmp_path: Path) -> list[dict[str, str]]:
    path = tmp_path / "logs" / "graph.log"
    assert path.exists()
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
