"""Read operations for the graph execution ledger."""

from __future__ import annotations

import csv
import io
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from hirocli.admin.shared.result import Result
from hirocli.domain.config import load_config, resolve_log_dir
from hirocli.domain.workspace import resolve_workspace
from hirocli.runtime.agent_graph.ledger import GRAPH_LEDGER_COLUMNS
from hirocli.runtime.agent_graph.tracing import langsmith_run_id

INITIAL_GRAPH_LEDGER_LINES = 100

log = Logger.get("ADMIN.GRAPH_RUNS")


@dataclass
class GraphLedgerSnapshot:
    rows: list[dict[str, Any]]
    file_offsets: dict[str, int]
    has_more: bool = False


@dataclass(frozen=True)
class GraphRunInspectSnapshot:
    """Node timeline plus the ``row_kind=run`` aggregate line for one ``run_id``."""

    timeline: list[dict[str, Any]]
    aggregate_row: dict[str, Any] | None


class GraphLedgerService:
    """Facade over ``<workspace>/logs/graph.log``."""

    def tail_initial(
        self,
        workspace: str | None,
        *,
        lines: int = INITIAL_GRAPH_LEDGER_LINES,
        since_seconds_ago: int | None = None,
        skip_from_end: int = 0,
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
            rows = _apply_filters(rows, {"row_kind": "run", **(filters or {})})
            rows.sort(key=lambda row: float(row.get("ts") or 0))
            page, has_more = _page_rows_from_end(rows, lines=lines, skip_from_end=skip_from_end)
            try:
                offset = path.stat().st_size
            except OSError as exc:
                log.warning(
                    "Unable to stat graph ledger while building initial tail",
                    path=str(path),
                    error=str(exc),
                )
                offset = 0
            return Result.success(
                GraphLedgerSnapshot(rows=page, file_offsets={str(path): offset}, has_more=has_more)
            )
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
            rows = _apply_filters(rows, {"row_kind": "run", **(filters or {})})
            return Result.success(
                GraphLedgerSnapshot(
                    rows=rows,
                    file_offsets={str(path): new_offset},
                    has_more=False,
                )
            )
        except RuntimeError:
            return Result.success(
                GraphLedgerSnapshot(rows=[], file_offsets=dict(file_offsets), has_more=False)
            )
        except Exception as exc:
            return Result.failure(str(exc))

    def inspect_run(
        self,
        workspace: str | None,
        run_id: str,
    ) -> Result[GraphRunInspectSnapshot]:
        """Return node rows ordered by step, and the latest aggregate row for the run."""
        rid = (run_id or "").strip()
        if not rid:
            return Result.failure("run_id is required.")
        try:
            path = _graph_log_path(workspace)
            payload = _inspect_run_rows(path, rid)
            return Result.success(payload)
        except Exception as exc:
            return Result.failure(str(exc))

    def retrieval_trace(
        self,
        workspace: str | None,
        run_id: str,
    ) -> Result[list[dict[str, Any]]]:
        """Return the per-stage Graphiti fact-search traces recorded for ``run_id``.

        Reads the JSONL sidecar written by ``graph_expand`` when retrieval tracing is
        enabled (one record per fact search, each tagged with its ``step_index`` so the
        UI can link a trace to its ledger row). Empty list when no sidecar exists — the
        common case, since tracing is opt-in."""
        rid = (run_id or "").strip()
        if not rid:
            return Result.failure("run_id is required.")
        try:
            from hirocli.services.knowledge.graph.retrieval_trace import read_trace_sidecar

            entry, _ = resolve_workspace(workspace)
            records = read_trace_sidecar(Path(entry.path), rid)
            return Result.success(records)
        except Exception as exc:
            return Result.failure(str(exc))

    def retrieval_loop(
        self,
        workspace: str | None,
        run_id: str,
    ) -> Result[dict[str, Any] | None]:
        """Return the FULL retrieval-recall detail for a CHAT recall run — the same shape the eval
        detail dialog renders: the loop trajectory (turns / sub-queries) PLUS the recalled
        facts/entities/episodes, the draft answer, and the render caps.

        Reads the two agent sidecars the recall node writes under observability=``trace``: the
        transcript (→ ``build_retrieval_loop_payload``) and the recalled-rows/draft companion (→
        ``read_agent_recall_result``, mirroring eval's ``row_json``). ``None`` when neither exists
        (tracing is opt-in). The per-sub-query pipeline detail stays reachable via the
        retrieval-trace endpoint (keyed by ``sid``)."""
        rid = (run_id or "").strip()
        if not rid:
            return Result.failure("run_id is required.")
        try:
            from hirocli.domain.preferences import load_preferences
            from hirocli.services.memory.agent.agent_trace import (
                build_retrieval_loop_payload,
                read_agent_recall_result,
                read_agent_retrieval_trace,
            )

            entry, _ = resolve_workspace(workspace)
            ws = Path(entry.path)
            events = read_agent_retrieval_trace(ws, rid)
            recall = read_agent_recall_result(ws, rid)
            if not events and not recall:
                return Result.success(None)
            prefs = load_preferences(ws)
            max_turns = int(prefs.memory.retrieval.limits.max_agent_turns)
            loop = (
                build_retrieval_loop_payload(events, max_agent_turns=max_turns) if events else None
            )
            render = prefs.memory.retrieval.render
            return Result.success(
                {
                    "loop": loop,
                    "recalled": recall.get("recalled") or [],
                    "answer": str(recall.get("answer") or ""),
                    "render": {
                        "max_elements_per_kind": int(
                            getattr(render, "max_elements_per_kind", 0) or 0
                        ),
                        "max_fact_chars": int(getattr(render, "max_fact_chars", 0) or 0),
                        "max_episode_chars": int(getattr(render, "max_episode_chars", 0) or 0),
                        "max_summary_chars": int(getattr(render, "max_summary_chars", 0) or 0),
                    },
                }
            )
        except Exception as exc:
            return Result.failure(str(exc))

    def ingest_trace(
        self,
        workspace: str | None,
        run_id: str,
    ) -> Result[list[dict[str, Any]]]:
        """Return the per-stage Graphiti ``add_episode`` traces recorded for ``run_id``.

        Reads the JSONL sidecar written by ``ingest_episodes`` when ingest tracing is
        enabled (one record per episode, each tagged with its ``step_index`` so the UI
        can link a trace to its episode ledger row). Empty list when no sidecar exists —
        the common case, since tracing is opt-in."""
        rid = (run_id or "").strip()
        if not rid:
            return Result.failure("run_id is required.")
        try:
            from hirocli.services.knowledge.graph.ingest_trace import read_ingest_trace_sidecar

            entry, _ = resolve_workspace(workspace)
            records = read_ingest_trace_sidecar(Path(entry.path), rid)
            return Result.success(records)
        except Exception as exc:
            return Result.failure(str(exc))


def _inspect_run_rows(path: Path, run_id: str) -> GraphRunInspectSnapshot:
    all_rows = _read_all_rows(path)
    nodes = [
        row
        for row in all_rows
        if row.get("run_id") == run_id and row.get("row_kind") == "node"
    ]
    # Secondary key keeps nested sub-step rows (e.g. ``4.1``, ``4.2``) ordered right after their
    # parent step and before the next top-level step.
    nodes.sort(key=lambda r: (int(r.get("step_index") or 0), int(r.get("sub_step") or 0)))
    aggregate_candidates = [
        row
        for row in all_rows
        if row.get("run_id") == run_id and row.get("row_kind") == "run"
    ]
    aggregate_row: dict[str, Any] | None = None
    if aggregate_candidates:
        aggregate_row = max(aggregate_candidates, key=lambda r: float(r.get("ts") or 0))
    return GraphRunInspectSnapshot(timeline=nodes, aggregate_row=aggregate_row)


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
    row["row_kind"] = row.get("row_kind") or "node"
    for key in ("ts", "stt_audio_seconds", "tts_audio_seconds", "cost_usd"):
        row[key] = _float_or_blank(row.get(key))
    for key in (
        "step_index",
        "sub_step",
        "node_attempt",
        "branch_index",
        "elapsed_ms",
        "chat_channel_id",
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
        "tts_chars",
        "tts_text_tokens",
        "tts_audio_tokens",
        "stt_audio_tokens",
    ):
        row[key] = _int_or_blank(row.get(key))
    # ``sub_step`` keeps ids unique when one parent step has several nested rows for the same node
    # (e.g. the same tool called twice → ``tools/search`` at ``8.1`` and ``8.2``).
    row["id"] = (
        f"{row.get('run_id')}:{row.get('row_kind')}:"
        f"{row.get('step_index')}.{row.get('sub_step')}:{row.get('node')}"
    )
    return row


def _page_rows_from_end(
    rows: list[dict[str, Any]],
    *,
    lines: int,
    skip_from_end: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Return ``lines`` run rows counting from the newest end, skipping ``skip_from_end`` first."""
    limit = max(1, int(lines))
    skip = max(0, int(skip_from_end))
    total = len(rows)
    end = max(0, total - skip)
    start = max(0, end - limit)
    return rows[start:end], start > 0


def _apply_filters(rows: list[dict[str, Any]], filters: dict[str, str]) -> list[dict[str, Any]]:
    active = {k: str(v).strip() for k, v in filters.items() if str(v or "").strip()}
    if not active:
        return rows
    out = rows
    for key in ("row_kind", "chat_channel_id", "character_id", "model", "decision_kind"):
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
    """Resolve the LangSmith **browser** URL for a ledger run via the official API (sync).

    The LangSmith run id is **UUID5(NAMESPACE_URL, ledger ``run_id``)** — the same value
    ``agent_manager`` passes as ``RunnableConfig["run_id"]`` so tracing and this lookup align.

    Requires ``LANGCHAIN_API_KEY`` or ``LANGSMITH_API_KEY`` (same as LangSmith ``Client()``).
    Returns ``None`` if the package is missing, credentials absent, or the run is not found yet.

    **Latency:** one ``read_run`` HTTP call (typically tens–hundreds of ms). Call from a worker
    thread (e.g. ``run_in_threadpool``) so the asyncio event loop is not blocked.
    """
    ledger_run_id = (run_id or "").strip()
    if not ledger_run_id:
        return None

    api_key = (
        os.environ.get("LANGCHAIN_API_KEY")
        or os.environ.get("LANGSMITH_API_KEY")
        or ""
    ).strip()
    if not api_key:
        return None

    try:
        from langsmith import Client
    except ImportError:
        log.debug("langsmith package not installed; omit LangSmith link")
        return None

    trace_id = str(langsmith_run_id(ledger_run_id))

    try:
        client = Client()
        run = client.read_run(trace_id, load_child_runs=False)
    except Exception as exc:
        # Run may not be ingested yet, or id mismatch — omit link rather than show a bad URL.
        log.debug(
            "LangSmith read_run failed — trace link omitted",
            error=str(exc),
            ledger_run_id=ledger_run_id,
            trace_id=trace_id,
        )
        return None

    try:
        direct = getattr(run, "url", None)
        if direct:
            out = str(direct).strip()
            if out:
                return out
        return client.get_run_url(run=run)
    except Exception as exc:
        log.debug(
            "LangSmith run URL could not be derived",
            error=str(exc),
            ledger_run_id=ledger_run_id,
            trace_id=trace_id,
        )
        return None
