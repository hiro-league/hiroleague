from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hirocli.admin.features.graph_runs.service import GraphLedgerService, langsmith_url_for_run
from hirocli.runtime.agent_graph.ledger import GRAPH_LEDGER_COLUMNS


def test_tail_initial_filters_rows(tmp_path: Path) -> None:
    _write_graph_log(
        tmp_path,
        [
            {
                "ts": "1000",
                "run_id": "chat-1",
                "step_index": "1",
                "node": "call_model",
                "chat_channel_id": "1",
                "character_id": "hiro",
                "model": "openai:gpt-5.4",
                "decision_kind": "text_reply",
            },
            {
                "ts": "1001",
                "run_id": "chat-2",
                "step_index": "1",
                "node": "tts",
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


def test_run_timeline_sorts_by_step_index(tmp_path: Path) -> None:
    _write_graph_log(
        tmp_path,
        [
            {"ts": "1002", "run_id": "chat-1", "step_index": "2", "node": "tools/search"},
            {"ts": "1000", "run_id": "chat-1", "step_index": "1", "node": "call_model"},
            {"ts": "1001", "run_id": "chat-other", "step_index": "1", "node": "call_model"},
        ],
    )

    with _workspace_patch(tmp_path):
        result = GraphLedgerService().run_timeline("ws", "chat-1")

    assert result.ok and result.data is not None
    assert [row["node"] for row in result.data] == ["call_model", "tools/search"]


def test_tail_initial_filters_before_line_limit(tmp_path: Path) -> None:
    _write_graph_log(
        tmp_path,
        [
            {"ts": "1000", "run_id": "chat-1", "step_index": "1", "node": "call_model", "model": "target"},
            {"ts": "1001", "run_id": "chat-2", "step_index": "1", "node": "call_model", "model": "other"},
            {"ts": "1002", "run_id": "chat-3", "step_index": "1", "node": "call_model", "model": "other"},
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


def test_langsmith_url_uses_configured_base_project(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_BASE_URL", "https://smith.example")
    monkeypatch.setenv("LANGSMITH_PROJECT", "Hiro Project")

    url = langsmith_url_for_run("chat-inbound-1")

    assert url is not None
    assert url.startswith("https://smith.example/projects/Hiro%20Project/r/")


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
