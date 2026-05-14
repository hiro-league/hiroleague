"""Read operations for the graph execution ledger."""

from __future__ import annotations

import csv
import io
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from hiro_commons.log import Logger

from hirocli.admin.shared.result import Result
from hirocli.domain.config import load_config, resolve_log_dir
from hirocli.domain.workspace import resolve_workspace
from hirocli.runtime.agent_graph.ledger import GRAPH_LEDGER_COLUMNS

INITIAL_GRAPH_LEDGER_LINES = 500

log = Logger.get("ADMIN.GRAPH_RUNS")


@dataclass
class GraphLedgerSnapshot:
    rows: list[dict[str, Any]]
    file_offsets: dict[str, int]


class GraphLedgerService:
    """Facade over ``<workspace>/logs/graph.log``."""

    def tail_initial(
        self,
        workspace: str | None,
        *,
        lines: int = INITIAL_GRAPH_LEDGER_LINES,
        since_seconds_ago: int | None = 86_400,
        filters: dict[str, str] | None = None,
    ) -> Result[GraphLedgerSnapshot]:
        try:
            path = _graph_log_path(workspace)
            min_ts = (
                time.time() - float(since_seconds_ago)
                if since_seconds_ago is not None
                else None
            )
            rows = _read_all_rows(path)
            if min_ts is not None:
                rows = [row for row in rows if float(row.get("ts") or 0) >= min_ts]
            rows = _apply_filters(rows, filters or {})
            rows.sort(key=lambda row: float(row.get("ts") or 0))
            if len(rows) > lines:
                rows = rows[-lines:]
            try:
                offset = path.stat().st_size
            except OSError as exc:
                log.warning(
                    "Unable to stat graph ledger while building initial tail",
                    path=str(path),
                    error=str(exc),
                )
                offset = 0
            return Result.success(GraphLedgerSnapshot(rows=rows, file_offsets={str(path): offset}))
        except Exception as exc:
            return Result.failure(str(exc))

    def tail_after_offsets(
        self,
        workspace: str | None,
        file_offsets: dict[str, int],
        *,
        filters: dict[str, str] | None = None,
    ) -> Result[GraphLedgerSnapshot]:
        try:
            path = _graph_log_path(workspace)
            offset = int(file_offsets.get(str(path), 0) if file_offsets else 0)
            rows, new_offset = _read_rows_from_offset(path, offset)
            rows = _apply_filters(rows, filters or {})
            return Result.success(
                GraphLedgerSnapshot(rows=rows, file_offsets={str(path): new_offset})
            )
        except RuntimeError:
            return Result.success(GraphLedgerSnapshot(rows=[], file_offsets=dict(file_offsets)))
        except Exception as exc:
            return Result.failure(str(exc))

    def run_timeline(
        self,
        workspace: str | None,
        run_id: str,
    ) -> Result[list[dict[str, Any]]]:
        rid = (run_id or "").strip()
        if not rid:
            return Result.failure("run_id is required.")
        try:
            path = _graph_log_path(workspace)
            rows = [row for row in _read_all_rows(path) if row.get("run_id") == rid]
            rows.sort(key=lambda r: int(r.get("step_index") or 0))
            return Result.success(rows)
        except Exception as exc:
            return Result.failure(str(exc))


def _graph_log_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    workspace_path = Path(entry.path)
    config = load_config(workspace_path)
    return resolve_log_dir(workspace_path, config) / "graph.log"


def _read_all_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as fh:
        return _read_csv_rows(fh)


def _read_rows_from_offset(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            fh.seek(max(0, offset))
            chunk = fh.read()
            new_offset = fh.tell()
    except OSError:
        return [], offset
    rows = _read_csv_rows(io.StringIO(chunk), fieldnames=GRAPH_LEDGER_COLUMNS) if chunk else []
    return rows, new_offset


def _read_csv_rows(source: Any, *, fieldnames: list[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in csv.DictReader(source, fieldnames=fieldnames):
        shaped = _shape_row(raw)
        if shaped is not None:
            rows.append(shaped)
    return rows


def _shape_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not raw or raw.get("ts") in {"ts", None, ""}:
        return None
    row = {column: raw.get(column, "") for column in GRAPH_LEDGER_COLUMNS}
    for key in ("ts", "stt_audio_seconds", "tts_audio_seconds", "cost_usd"):
        row[key] = _float_or_blank(row.get(key))
    for key in (
        "step_index",
        "node_attempt",
        "branch_index",
        "elapsed_ms",
        "chat_channel_id",
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
        "tts_chars",
    ):
        row[key] = _int_or_blank(row.get(key))
    row["id"] = f"{row.get('run_id')}:{row.get('step_index')}:{row.get('node')}"
    return row


def _apply_filters(rows: list[dict[str, Any]], filters: dict[str, str]) -> list[dict[str, Any]]:
    active = {k: str(v).strip() for k, v in filters.items() if str(v or "").strip()}
    if not active:
        return rows
    out = rows
    for key in ("chat_channel_id", "character_id", "model", "decision_kind"):
        value = active.get(key)
        if not value:
            continue
        out = [row for row in out if str(row.get(key) or "") == value]
    return out


def _int_or_blank(value: Any) -> int | str:
    if value in ("", None):
        return ""
    try:
        return int(value)
    except (TypeError, ValueError):
        return ""


def _float_or_blank(value: Any) -> float | str:
    if value in ("", None):
        return ""
    try:
        return float(value)
    except (TypeError, ValueError):
        return ""


def langsmith_url_for_run(run_id: str) -> str | None:
    """Build a LangSmith deep link when base URL and project are configured."""
    base_url = (
        os.environ.get("LANGSMITH_BASE_URL")
        or os.environ.get("LANGCHAIN_ENDPOINT")
        or ""
    ).strip()
    project = (
        os.environ.get("LANGSMITH_PROJECT")
        or os.environ.get("LANGCHAIN_PROJECT")
        or ""
    ).strip()
    if not base_url or not project:
        return None
    langsmith_run_id = uuid.uuid5(uuid.NAMESPACE_URL, run_id)
    return f"{base_url.rstrip('/')}/projects/{quote(project)}/r/{langsmith_run_id}"
