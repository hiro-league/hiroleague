"""Unit tests for the persisted memory-eval result store (per-corpus snapshot)."""

from __future__ import annotations

from pathlib import Path

from hirocli.services.eval.store import (
    EvalResultStore,
    coalesce_ingested_ranges,
    eval_results_db_path,
    get_eval_result_store,
)


def _row(
    qid: str,
    mark: str,
    answer: str = "a",
    cost: float = 0.01,
    *,
    negative_control: bool = False,
) -> dict:
    """A minimal question_completed-shaped row for the store."""
    return {
        "id": qid,
        "index": 0,
        "total": 1,
        "category": "recall",
        "question": f"q-{qid}",
        "gold": "g",
        "track": "memory",
        "cost_usd": cost,
        "is_negative_control": negative_control,
        "legs": {"recall": {"mode": "recall", "mark": mark, "answer": answer, "cost_usd": cost}},
    }


def test_db_path_under_workspace_knowledge_dir(tmp_path: Path) -> None:
    assert eval_results_db_path(tmp_path) == tmp_path / "knowledge" / "eval_results.db"


def test_upsert_read_roundtrip(tmp_path: Path) -> None:
    store = EvalResultStore(tmp_path / "knowledge" / "eval_results.db")
    store.upsert_row("adam", "q1", _row("q1", "✓"), mark="✓", cost_usd=0.01)
    store.upsert_row("adam", "q2", _row("q2", "✗"), mark="✗", cost_usd=0.02)

    rows = store.read_corpus("adam")
    assert set(rows) == {"q1", "q2"}
    assert rows["q1"]["legs"]["recall"]["mark"] == "✓"
    # Parent dir is created lazily on first write.
    assert (tmp_path / "knowledge" / "eval_results.db").exists()


def test_find_row_by_run_id_resolves_recall_node(tmp_path: Path) -> None:
    """The Graph-Runs → eval-detail bridge resolves a memory_recall node's run_id back to its row."""
    store = EvalResultStore(tmp_path / "knowledge" / "eval_results.db")
    r1 = _row("q1", "✓")
    r1["legs"]["recall"]["run_id"] = "memory_eval_q-adam-run42-q1"
    r2 = _row("q2", "✗")
    r2["legs"]["recall"]["run_id"] = "memory_eval_q-adam-run42-q2"
    store.upsert_row("adam", "q1", r1, mark="✓", cost_usd=0.01)
    store.upsert_row("adam", "q2", r2, mark="✗", cost_usd=0.02)

    found = store.find_row_by_run_id("memory_eval_q-adam-run42-q2")
    assert found is not None
    assert found["id"] == "q2"
    assert found["corpus_id"] == "adam"  # injected so the bridge knows which corpus it came from
    # A run_id with no saved row (cleared / never run) resolves to None, not a wrong row.
    assert store.find_row_by_run_id("memory_eval_q-adam-run42-missing") is None


def test_rerun_upserts_in_place_and_keeps_others(tmp_path: Path) -> None:
    """Re-running one question overwrites only its row; the rest of the corpus stays."""
    store = EvalResultStore(tmp_path / "knowledge" / "eval_results.db")
    store.upsert_row("adam", "q1", _row("q1", "✗", answer="old"), mark="✗", cost_usd=0.01)
    store.upsert_row("adam", "q2", _row("q2", "✓"), mark="✓", cost_usd=0.01)

    # Re-run q1 only → its row updates, q2 untouched.
    store.upsert_row("adam", "q1", _row("q1", "✓", answer="new"), mark="✓", cost_usd=0.03)

    rows = store.read_corpus("adam")
    assert len(rows) == 2
    assert rows["q1"]["legs"]["recall"]["mark"] == "✓"
    assert rows["q1"]["legs"]["recall"]["answer"] == "new"
    assert rows["q2"]["legs"]["recall"]["mark"] == "✓"


def test_corpus_isolation(tmp_path: Path) -> None:
    store = EvalResultStore(tmp_path / "knowledge" / "eval_results.db")
    store.upsert_row("adam", "q1", _row("q1", "✓"), mark="✓", cost_usd=0.0)
    store.upsert_row("other", "q1", _row("q1", "✗"), mark="✗", cost_usd=0.0)

    assert store.read_corpus("adam")["q1"]["legs"]["recall"]["mark"] == "✓"
    assert store.read_corpus("other")["q1"]["legs"]["recall"]["mark"] == "✗"


def test_clear_corpus_is_results_only_and_scoped(tmp_path: Path) -> None:
    store = EvalResultStore(tmp_path / "knowledge" / "eval_results.db")
    store.upsert_row("adam", "q1", _row("q1", "✓"), mark="✓", cost_usd=0.0)
    store.upsert_row("adam", "q2", _row("q2", "✓"), mark="✓", cost_usd=0.0)
    store.upsert_row("other", "q1", _row("q1", "✓"), mark="✓", cost_usd=0.0)

    removed = store.clear_corpus("adam")
    assert removed == 2
    assert store.read_corpus("adam") == {}
    # A different corpus is unaffected by the clear.
    assert set(store.read_corpus("other")) == {"q1"}


def test_read_missing_db_is_empty(tmp_path: Path) -> None:
    store = EvalResultStore(tmp_path / "knowledge" / "eval_results.db")
    # No writes yet → no DB file → empty read, no crash.
    assert store.read_corpus("adam") == {}
    assert store.clear_corpus("adam") == 0


def test_blank_ids_are_ignored(tmp_path: Path) -> None:
    store = EvalResultStore(tmp_path / "knowledge" / "eval_results.db")
    store.upsert_row("", "q1", _row("q1", "✓"), mark="✓", cost_usd=0.0)
    store.upsert_row("adam", "", _row("", "✓"), mark="✓", cost_usd=0.0)
    assert store.read_corpus("adam") == {}


def test_get_eval_result_store_is_cached_per_workspace(tmp_path: Path) -> None:
    a = get_eval_result_store(tmp_path)
    b = get_eval_result_store(tmp_path)
    assert a is b


def test_ingested_ranges_append_upsert_and_read(tmp_path: Path) -> None:
    store = EvalResultStore(tmp_path / "knowledge" / "eval_results.db")
    store.append_range("adam", 0, 50, 0.10)
    store.append_range("adam", 50, 50, 0.20)
    assert store.read_ranges("adam") == [
        {"start": 0, "count": 50, "cost_usd": 0.10},
        {"start": 50, "count": 50, "cost_usd": 0.20},
    ]
    # Re-running the SAME offset upserts that batch's count AND cost (no duplicate row stacking,
    # and the cumulative never double-counts a re-ingested offset).
    store.append_range("adam", 0, 100, 0.35)
    assert store.read_ranges("adam") == [
        {"start": 0, "count": 100, "cost_usd": 0.35},
        {"start": 50, "count": 50, "cost_usd": 0.20},
    ]
    # Cumulative per-corpus ingest cost = sum of every batch's cost.
    assert sum(r["cost_usd"] for r in store.read_ranges("adam")) == 0.55
    # Empty/invalid batches are ignored.
    store.append_range("adam", 200, 0)
    store.append_range("adam", -1, 5)
    assert [r["start"] for r in store.read_ranges("adam")] == [0, 50]


def test_ingested_ranges_clear_and_isolation(tmp_path: Path) -> None:
    store = EvalResultStore(tmp_path / "knowledge" / "eval_results.db")
    store.append_range("adam", 0, 50)
    store.append_range("other", 0, 10)
    # Clearing ranges is corpus-scoped and independent of the results table.
    store.upsert_row("adam", "q1", _row("q1", "✓"), mark="✓", cost_usd=0.0)
    removed = store.clear_ranges("adam")
    assert removed == 1
    assert store.read_ranges("adam") == []
    assert store.read_ranges("other") == [{"start": 0, "count": 10, "cost_usd": 0.0}]
    # Range clear leaves the saved question rows untouched (separate concern).
    assert set(store.read_corpus("adam")) == {"q1"}


def test_ranges_survive_preexisting_db_without_the_table(tmp_path: Path) -> None:
    """A DB created before the ranges table existed must not crash range reads/clears
    (no-migration: the table is created on access)."""
    import sqlite3

    db = tmp_path / "knowledge" / "eval_results.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    # Simulate the OLD schema: only the results table, no memory_eval_ingested_ranges.
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE memory_eval_results (corpus_id TEXT, question_id TEXT, "
            "row_json TEXT, mark TEXT, cost_usd REAL, updated_at TEXT, "
            "PRIMARY KEY (corpus_id, question_id))"
        )
    store = EvalResultStore(db)
    # Previously raised sqlite3.OperationalError: no such table.
    assert store.read_ranges("adam") == []
    assert store.clear_ranges("adam") == 0
    # And the table is now usable.
    store.append_range("adam", 0, 5)
    assert store.read_ranges("adam") == [{"start": 0, "count": 5, "cost_usd": 0.0}]


def test_coalesce_ingested_ranges_merges_and_keeps_gaps() -> None:
    # Contiguous (0–49 + 50–99) and overlapping batches fold; a gap stays visible.
    spans = coalesce_ingested_ranges(
        [{"start": 50, "count": 50}, {"start": 0, "count": 50}, {"start": 150, "count": 50}]
    )
    assert spans == [[0, 99], [150, 199]]
    # Overlap folds to the wider end; a zero-count batch is dropped.
    assert coalesce_ingested_ranges(
        [{"start": 0, "count": 100}, {"start": 50, "count": 10}, {"start": 300, "count": 0}]
    ) == [[0, 99]]
    assert coalesce_ingested_ranges([]) == []


def test_summarize_memory_rows_merged_snapshot() -> None:
    """The merged read recomputes correct-count + infers judged from the marks."""
    from hirocli.services.eval.runner import summarize_memory_rows

    # q3 abstains on a NORMAL question (miss); q4 abstains on a negative control (correct).
    rows = [
        _row("q1", "✓"),
        _row("q2", "✗"),
        _row("q3", "🛇"),
        _row("q4", "🛇", negative_control=True),
    ]
    s = summarize_memory_rows(rows, run_id="saved-adam")
    assert s["track"] == "memory"
    assert s["total_questions"] == 4
    assert s["gate"] == "n/a"
    assert s["judged"] is True  # marks present → judged inferred
    # Correct = ✓ + correct-abstain (the control). The non-control 🛇 is NOT correct (bug fix).
    assert s["passing"]["recall"] == 2
    # Raw mark distribution still bins both abstains under 'abstain'.
    assert s["groups"]["recall"] == {"pass": 1, "partial": 0, "fail": 1, "abstain": 2}
    assert s["scoring"]["recall"] == 2.0


def test_summarize_memory_rows_judge_off_inference() -> None:
    """No marks anywhere → judged inferred False (answers-only snapshot)."""
    from hirocli.services.eval.runner import summarize_memory_rows

    rows = [_row("q1", ""), _row("q2", "")]
    s = summarize_memory_rows(rows, run_id="saved-adam")
    assert s["judged"] is False
    assert s["passing"]["recall"] == 0
