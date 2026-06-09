"""Unit tests for the persisted memory-eval result store (per-corpus snapshot)."""

from __future__ import annotations

from pathlib import Path

from hirocli.services.knowledge.eval_store import (
    EvalResultStore,
    eval_results_db_path,
    get_eval_result_store,
)


def _row(qid: str, mark: str, answer: str = "a", cost: float = 0.01) -> dict:
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


def test_summarize_memory_rows_merged_snapshot() -> None:
    """The merged read recomputes pass-count + infers judged from the marks."""
    from hirocli.services.knowledge.eval_runner import summarize_memory_rows

    rows = [_row("q1", "✓"), _row("q2", "✗"), _row("q3", "🛇")]
    s = summarize_memory_rows(rows, run_id="saved-adam")
    assert s["track"] == "memory"
    assert s["total_questions"] == 3
    assert s["gate"] == "n/a"
    assert s["judged"] is True  # marks present → judged inferred
    # ✓ and 🛇 (abstain) are the passing marks; ✗ is not.
    assert s["passing"]["recall"] == 2


def test_summarize_memory_rows_judge_off_inference() -> None:
    """No marks anywhere → judged inferred False (answers-only snapshot)."""
    from hirocli.services.knowledge.eval_runner import summarize_memory_rows

    rows = [_row("q1", ""), _row("q2", "")]
    s = summarize_memory_rows(rows, run_id="saved-adam")
    assert s["judged"] is False
    assert s["passing"]["recall"] == 0
