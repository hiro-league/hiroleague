from __future__ import annotations

import csv
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hirocli.admin.features.graph_runs.service import (
    GraphLedgerService,
    langsmith_url_for_run,
)
from hirocli.runtime.agent_graph.ledger import GRAPH_LEDGER_COLUMNS


def test_tail_initial_filters_rows(tmp_path: Path) -> None:
    _write_graph_log(
        tmp_path,
        [
            {
                "ts": "1000",
                "run_id": "chat-1",
                "row_kind": "run",
                "step_index": "1",
                "node": "@run",
                "chat_channel_id": "1",
                "character_id": "hiro",
                "model": "openai:gpt-5.4",
                "decision_kind": "text_reply",
            },
            {
                "ts": "1001",
                "run_id": "chat-2",
                "row_kind": "run",
                "step_index": "1",
                "node": "@run",
                "chat_channel_id": "2",
                "character_id": "mika",
                "model": "openai:tts-1",
                "tts_audio_seconds": "2.5",
                "decision_kind": "voiced",
            },
        ],
    )

    with (
        _workspace_patch(tmp_path),
        patch("hirocli.admin.features.graph_runs.service.time.time", return_value=2000),
    ):
        result = GraphLedgerService().tail_initial(
            "ws",
            since_seconds_ago=None,
            filters={"chat_channel_id": "2", "decision_kind": "voiced"},
        )

    assert result.ok and result.data is not None
    assert [row["run_id"] for row in result.data.rows] == ["chat-2"]
    assert result.data.rows[0]["tts_audio_seconds"] == 2.5
    assert result.data.file_offsets


def test_inspect_run_sorts_nodes_and_returns_aggregate(tmp_path: Path) -> None:
    _write_graph_log(
        tmp_path,
        [
            {"ts": "1003", "run_id": "chat-1", "row_kind": "run", "node": "@run"},
            {"ts": "1002", "run_id": "chat-1", "step_index": "2", "node": "tools/search"},
            {"ts": "1000", "run_id": "chat-1", "step_index": "1", "node": "call_model"},
            {"ts": "1001", "run_id": "chat-other", "step_index": "1", "node": "call_model"},
        ],
    )

    with _workspace_patch(tmp_path):
        result = GraphLedgerService().inspect_run("ws", "chat-1")

    assert result.ok and result.data is not None
    assert [row["node"] for row in result.data.timeline] == ["call_model", "tools/search"]
    assert result.data.aggregate_row is not None
    assert result.data.aggregate_row.get("node") == "@run"


def test_tail_initial_skip_from_end_pages(tmp_path: Path) -> None:
    rows = [
        {
            "ts": str(1000 + index),
            "run_id": f"chat-{index}",
            "row_kind": "run",
            "node": "@run",
        }
        for index in range(150)
    ]
    _write_graph_log(tmp_path, rows)

    with _workspace_patch(tmp_path):
        first = GraphLedgerService().tail_initial("ws", lines=100, skip_from_end=0)
        second = GraphLedgerService().tail_initial("ws", lines=100, skip_from_end=100)

    assert first.ok and first.data is not None
    assert [row["run_id"] for row in first.data.rows] == [f"chat-{index}" for index in range(50, 150)]
    assert first.data.has_more is True

    assert second.ok and second.data is not None
    assert [row["run_id"] for row in second.data.rows] == [f"chat-{index}" for index in range(50)]
    assert second.data.has_more is False


def test_tail_initial_filters_before_line_limit(tmp_path: Path) -> None:
    _write_graph_log(
        tmp_path,
        [
            {"ts": "1000", "run_id": "chat-1", "row_kind": "run", "node": "@run", "model": "target"},
            {"ts": "1001", "run_id": "chat-2", "row_kind": "run", "node": "@run", "model": "other"},
            {"ts": "1002", "run_id": "chat-3", "row_kind": "run", "node": "@run", "model": "other"},
        ],
    )

    with _workspace_patch(tmp_path):
        result = GraphLedgerService().tail_initial(
            "ws",
            lines=1,
            since_seconds_ago=None,
            filters={"model": "target"},
        )

    assert result.ok and result.data is not None
    assert [row["run_id"] for row in result.data.rows] == ["chat-1"]


def test_langsmith_url_none_without_api_key(monkeypatch) -> None:
    for key in ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    assert langsmith_url_for_run("chat-inbound-1") is None


def test_langsmith_url_prefers_run_url_from_client(monkeypatch) -> None:
    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-key")
    ledger_id = "chat-xyz"
    trace_id = str(uuid.uuid5(uuid.NAMESPACE_URL, ledger_id))
    mock_run = MagicMock()
    mock_run.url = "https://smith.example/o/org/projects/p/p/r/x"

    with patch("langsmith.Client") as client_cls:
        client_cls.return_value.read_run.return_value = mock_run
        assert langsmith_url_for_run(ledger_id) == mock_run.url
        client_cls.return_value.read_run.assert_called_once_with(trace_id, load_child_runs=False)


def test_langsmith_url_uses_get_run_url_when_no_direct_url(monkeypatch) -> None:
    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-key")
    mock_run = MagicMock()
    mock_run.url = None

    with patch("langsmith.Client") as client_cls:
        inst = client_cls.return_value
        inst.read_run.return_value = mock_run
        inst.get_run_url.return_value = "https://smith.example/built"
        assert langsmith_url_for_run("chat-a") == "https://smith.example/built"
        inst.get_run_url.assert_called_once_with(run=mock_run)


def test_langsmith_url_none_when_read_run_fails(monkeypatch) -> None:
    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-key")
    with patch("langsmith.Client") as client_cls:
        client_cls.return_value.read_run.side_effect = OSError("network")
        assert langsmith_url_for_run("chat-b") is None


def _write_graph_log(tmp_path: Path, rows: list[dict[str, str]]) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    path = log_dir / "graph.log"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=GRAPH_LEDGER_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in GRAPH_LEDGER_COLUMNS})


def _workspace_patch(tmp_path: Path):
    return patch(
        "hirocli.admin.features.graph_runs.service.resolve_workspace",
        return_value=(SimpleNamespace(path=str(tmp_path)), None),
    )
