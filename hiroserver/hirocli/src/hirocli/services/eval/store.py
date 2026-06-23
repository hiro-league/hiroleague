"""Per-workspace SQLite store for persisted MEMORY-track eval results.

Why this exists
---------------
The in-memory :mod:`eval_registry` keeps only the *latest* run per workspace and
drops everything on restart. For the memory track we want results to **survive a
restart** and to **accumulate per corpus**: pick a corpus and see its latest
results; re-run a subset of questions and have those rows update in place while
the rest stay — so the saved snapshot grows more complete over time without ever
re-running every question. (Design: per-corpus persisted memory eval results.)

Model — a single living snapshot per corpus
-------------------------------------------
One row per ``(corpus_id, question_id)``. A re-run **upserts** the question's row
(add new / overwrite existing); there is NO run history. The full
``question_completed`` payload is stored verbatim as ``row_json`` (it already has
everything the panel renders — legs, recalled facts, answer, judge mark, cost),
so reads are a plain JSON load. ``mark``/``cost_usd`` are denormalized into
columns purely so the read path can recompute the merged summary cheaply.

Scope: memory track only for now, but the schema is corpus-keyed and
track-agnostic so the knowledge track can adopt it later without a migration.
We're in initial-development mode (no backward-compat / no migration shims).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from hirocli.services.knowledge.constants import KNOWLEDGE_DIR
from hirocli.services.knowledge.converters import utc_now_iso

log = Logger.get("SVC.KNOWLEDGE.EVAL.STORE")

# Lives beside the catalog DB (``knowledge/knowledge.db``) under the workspace's
# knowledge dir. Separate file from the catalog so eval is fully isolated.
EVAL_DB_FILENAME = "eval_results.db"


def eval_results_db_path(workspace_path: Path) -> Path:
    """Resolve the per-workspace eval-results DB path (``knowledge/eval_results.db``)."""
    return Path(workspace_path) / KNOWLEDGE_DIR / EVAL_DB_FILENAME


class EvalResultStore:
    """Source of truth for persisted memory-eval results in ``eval_results.db``."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def ensure_schema(self) -> None:
        # Parent dir may not exist yet on a brand-new workspace (catalog creates it
        # lazily too) — make it before opening the DB so the first write can't fail.
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_eval_results (
                  corpus_id    TEXT NOT NULL,
                  question_id  TEXT NOT NULL,
                  -- Full eval.question_completed payload (legs/answer/recalled/gold/…).
                  row_json     TEXT NOT NULL,
                  -- Denormalized for cheap summary recompute / checklist badges on read.
                  mark         TEXT NOT NULL DEFAULT '',
                  cost_usd     REAL NOT NULL DEFAULT 0,
                  updated_at   TEXT NOT NULL,
                  PRIMARY KEY (corpus_id, question_id)
                );
                -- Ingested episode batches per corpus (one row per remember batch). Tracks WHICH
                -- episodes of a turn corpus have been remembered into the graph, so the panel can
                -- print the ingested range — remember-only batches write no question rows, so this
                -- is the only record of build progress. Keyed by (corpus_id, start) so re-running
                -- the same offset updates that batch's count instead of stacking duplicates. RESET
                -- whenever the graph is wiped (clear_before / eval clear) so the range never lies.
                CREATE TABLE IF NOT EXISTS memory_eval_ingested_ranges (
                  corpus_id     TEXT NOT NULL,
                  start         INTEGER NOT NULL,
                  count         INTEGER NOT NULL,
                  -- This batch's ingest (graph-build) cost in USD. Summed across batches for the
                  -- panel's CUMULATIVE per-corpus ingest cost — the only place ingest cost survives
                  -- a reload (the per-question results table never holds it). Reset with the ranges
                  -- on a graph wipe, so the cumulative can't outlive the data it paid for.
                  cost_usd      REAL NOT NULL DEFAULT 0,
                  updated_at    TEXT NOT NULL,
                  PRIMARY KEY (corpus_id, start)
                );
                """
            )
            # No-migration mode, but a ranges table created before cost_usd existed would have
            # CREATE TABLE IF NOT EXISTS skip the new column → read_ranges' SELECT cost_usd crashes.
            # Reconcile additively (no data migration — existing rows default to 0) so an older
            # eval_results.db keeps its saved results instead of forcing a workspace wipe.
            cols = {r["name"] for r in con.execute("PRAGMA table_info(memory_eval_ingested_ranges)")}
            if "cost_usd" not in cols:
                con.execute(
                    "ALTER TABLE memory_eval_ingested_ranges ADD COLUMN cost_usd REAL NOT NULL DEFAULT 0"
                )

    def upsert_row(
        self,
        corpus_id: str,
        question_id: str,
        row: dict[str, Any],
        *,
        mark: str,
        cost_usd: float,
    ) -> None:
        """Insert or overwrite one question's result for ``corpus_id`` (the merge step)."""
        if not corpus_id or not question_id:
            return
        self.ensure_schema()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO memory_eval_results
                  (corpus_id, question_id, row_json, mark, cost_usd, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(corpus_id, question_id) DO UPDATE SET
                  row_json   = excluded.row_json,
                  mark       = excluded.mark,
                  cost_usd   = excluded.cost_usd,
                  updated_at = excluded.updated_at
                """,
                (
                    corpus_id,
                    question_id,
                    json.dumps(row),
                    mark or "",
                    float(cost_usd or 0.0),
                    utc_now_iso(),
                ),
            )

    def read_corpus(self, corpus_id: str) -> dict[str, dict[str, Any]]:
        """Return ``{question_id: stored row dict}`` for ``corpus_id`` (empty if none)."""
        if not corpus_id or not self.db_path.exists():
            return {}
        with self.connect() as con:
            rows = con.execute(
                "SELECT question_id, row_json FROM memory_eval_results WHERE corpus_id = ?",
                (corpus_id,),
            ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            try:
                out[str(r["question_id"])] = json.loads(r["row_json"])
            except (json.JSONDecodeError, TypeError):
                # A single corrupt row must not sink the whole corpus read.
                log.warning(
                    "⚠️ knowledge.eval — skipping unreadable stored row · corpus=%s · qid=%s",
                    corpus_id,
                    r["question_id"],
                )
        return out

    def find_row_by_run_id(self, run_id: str) -> dict[str, Any] | None:
        """Find the saved question row whose ANY leg ran under ``run_id`` (the per-question graph
        run id stamped on ``leg.run_id``).

        Backs the Graph-Runs → eval-detail bridge: a ``memory_recall`` graph-run node carries that
        per-question ``run_id``, and this resolves it back to the full saved row so the rich eval
        detail dialog can open in place. ``LIKE`` pre-filters candidate rows (run_id is embedded in
        the JSON), then we confirm by parsing so a substring collision can't return a wrong row.
        Returns the parsed row dict (with ``corpus_id`` injected) or ``None`` if no row matches."""
        rid = (run_id or "").strip()
        if not rid or not self.db_path.exists():
            return None
        with self.connect() as con:
            rows = con.execute(
                "SELECT corpus_id, question_id, row_json FROM memory_eval_results "
                "WHERE row_json LIKE ?",
                (f"%{rid}%",),
            ).fetchall()
        for r in rows:
            try:
                row = json.loads(r["row_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            legs = row.get("legs") if isinstance(row.get("legs"), dict) else {}
            if any(str((leg or {}).get("run_id") or "") == rid for leg in legs.values()):
                row["corpus_id"] = r["corpus_id"]
                return row
        return None

    def clear_corpus(self, corpus_id: str) -> int:
        """Delete all persisted results for ``corpus_id`` (the "Clear results" action).

        Returns the number of question rows removed. Results-only: the ingested
        memory drawer is a separate concern and is left untouched."""
        if not corpus_id or not self.db_path.exists():
            return 0
        with self.connect() as con:
            cur = con.execute(
                "DELETE FROM memory_eval_results WHERE corpus_id = ?", (corpus_id,)
            )
            return int(cur.rowcount or 0)

    # --- Ingested episode ranges (build progress) -------------------------------------------

    def append_range(
        self, corpus_id: str, start: int, count: int, cost_usd: float = 0.0
    ) -> None:
        """Record that a remember batch ingested ``count`` episodes starting at ``start``,
        at ``cost_usd`` (this batch's graph-build cost).

        Upsert on ``(corpus_id, start)`` so re-running the same offset overwrites that batch's
        count AND cost rather than stacking a duplicate row (so the cumulative never double-counts
        a re-ingested offset). No-op for empty/invalid batches."""
        if not corpus_id or count <= 0 or start < 0:
            return
        self.ensure_schema()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO memory_eval_ingested_ranges
                  (corpus_id, start, count, cost_usd, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(corpus_id, start) DO UPDATE SET
                  count      = excluded.count,
                  cost_usd   = excluded.cost_usd,
                  updated_at = excluded.updated_at
                """,
                (corpus_id, int(start), int(count), float(cost_usd or 0.0), utc_now_iso()),
            )

    def read_ranges(self, corpus_id: str) -> list[dict[str, float]]:
        """Return the recorded ingest batches for ``corpus_id`` as ``[{start, count, cost_usd}]``,
        ordered by start (empty if none / no DB yet)."""
        if not corpus_id or not self.db_path.exists():
            return []
        # The DB file may predate this table (added after the results table). No-migration mode:
        # create-on-access so a read never trips "no such table" on an older eval_results.db.
        self.ensure_schema()
        with self.connect() as con:
            rows = con.execute(
                "SELECT start, count, cost_usd FROM memory_eval_ingested_ranges "
                "WHERE corpus_id = ? ORDER BY start",
                (corpus_id,),
            ).fetchall()
        return [
            {
                "start": int(r["start"]),
                "count": int(r["count"]),
                "cost_usd": float(r["cost_usd"] or 0.0),
            }
            for r in rows
        ]

    def clear_ranges(self, corpus_id: str) -> int:
        """Drop all ingested-range records for ``corpus_id`` (called whenever the graph is
        wiped, so the printed range resets in lock-step). Returns rows removed."""
        if not corpus_id or not self.db_path.exists():
            return 0
        # Create-on-access (see read_ranges) so a reset on an older DB can't fail on a missing table.
        self.ensure_schema()
        with self.connect() as con:
            cur = con.execute(
                "DELETE FROM memory_eval_ingested_ranges WHERE corpus_id = ?", (corpus_id,)
            )
            return int(cur.rowcount or 0)


def coalesce_ingested_ranges(ranges: list[dict[str, int]]) -> list[list[int]]:
    """Merge ``[{start, count}]`` batches into sorted, INCLUSIVE ``[start, end]`` spans.

    Contiguous/overlapping batches fold together (0–49 + 50–99 → 0–99); gaps stay visible
    (0–99, 150–199) so a missed range is obvious. End is the last ingested index (start+count-1)."""
    spans = sorted(
        ([int(r["start"]), int(r["start"]) + int(r["count"]) - 1] for r in ranges if int(r["count"]) > 0),
        key=lambda s: s[0],
    )
    merged: list[list[int]] = []
    for start, end in spans:
        # Fold into the previous span when it touches or overlaps it (gap of 1 = contiguous).
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


# Process-wide cache of one store per workspace (mirrors how the registry is a
# singleton). ensure_schema is idempotent, so a cache miss just rebuilds cheaply.
_STORES: dict[str, EvalResultStore] = {}


def get_eval_result_store(workspace_path: Path) -> EvalResultStore:
    """Return the cached :class:`EvalResultStore` for ``workspace_path``."""
    try:
        key = str(Path(workspace_path).resolve())
    except OSError:
        key = str(Path(workspace_path))
    store = _STORES.get(key)
    if store is None:
        store = EvalResultStore(eval_results_db_path(Path(workspace_path)))
        _STORES[key] = store
    return store
