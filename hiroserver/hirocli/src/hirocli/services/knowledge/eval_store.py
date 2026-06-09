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
                  -- Full knowledge.eval.question_completed payload (legs/answer/recalled/gold/…).
                  row_json     TEXT NOT NULL,
                  -- Denormalized for cheap summary recompute / checklist badges on read.
                  mark         TEXT NOT NULL DEFAULT '',
                  cost_usd     REAL NOT NULL DEFAULT 0,
                  updated_at   TEXT NOT NULL,
                  PRIMARY KEY (corpus_id, question_id)
                );
                """
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
