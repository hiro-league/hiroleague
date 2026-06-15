from __future__ import annotations

import json
from pathlib import Path

import pytest

from hirocli.services.knowledge.eval_locomo import (
    LocomoExportError,
    build_locomo_results_export,
    compute_evidence_recall_map,
)


def _write_locomo_files(tmp_path: Path) -> Path:
    questions = tmp_path / "locomo_conv_43.questions.yaml"
    questions.write_text(
        """
- id: locomo_conv_43_q001_c1
  category: multi_hop
  question: What did John want?
  expected_answer: a championship
  requires: [graph]
- id: locomo_conv_43_q002_c2
  category: temporal
  question: When did Tim leave?
  expected_answer: June
  requires: [temporal]
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "locomo_conv_43.locomo.yaml").write_text(
        """
source:
  dataset: LoCoMo
  sample_id: conv-43
  original: locomo10.json
category_mapping:
  1: multi_hop
  2: temporal
questions:
  locomo_conv_43_q001_c1:
    sample_id: conv-43
    question_index: 0
    category: 1
    evidence:
      dia_ids: [D1:9]
      episode_ids: [locomo_conv_43_d1_9]
  locomo_conv_43_q002_c2:
    sample_id: conv-43
    question_index: 1
    category: 2
    evidence:
      dia_ids: [D2:1]
      episode_ids: [locomo_conv_43_d2_1]
episodes:
  locomo_conv_43_d1_9:
    sample_id: conv-43
    session: 1
    dia_id: D1:9
  locomo_conv_43_d2_1:
    sample_id: conv-43
    session: 2
    dia_id: D2:1
""".lstrip(),
        encoding="utf-8",
    )
    return questions


def _saved_row(qid: str, answer: str, chunk_id: str | None = None) -> dict:
    recalled = []
    if chunk_id:
        recalled.append({"memory": "supporting fact", "kind": "fact", "chunk_id": chunk_id})
    return {
        "id": qid,
        "track": "memory",
        "legs": {
            "recall": {
                "mode": "recall",
                "answer": answer,
                "mark": "",
                "recalled": recalled,
            }
        },
    }


def test_build_locomo_results_export_uses_exact_sample_qa_shape(tmp_path: Path) -> None:
    qpath = _write_locomo_files(tmp_path)
    export = build_locomo_results_export(
        corpus_id="locomo_conv_43",
        questions_path=qpath,
        stored_rows={
            "locomo_conv_43_q001_c1": _saved_row(
                "locomo_conv_43_q001_c1", "John wanted to win a championship.", "locomo_conv_43_d1_9"
            )
        },
    )

    assert export["exported_count"] == 1
    assert export["total_count"] == 2
    assert export["partial"] is True
    payload = json.loads(export["content"])
    assert payload == [
        {
            "sample_id": "conv-43",
            "qa": [
                {
                    "question": "What did John want?",
                    "answer": "a championship",
                    "category": 1,
                    "evidence": ["D1:9"],
                    "hiro_memory_prediction": "John wanted to win a championship.",
                    "hiro_memory_prediction_context": ["D1:9"],
                }
            ],
        }
    ]


def test_build_locomo_results_export_custom_prediction_key(tmp_path: Path) -> None:
    qpath = _write_locomo_files(tmp_path)
    export = build_locomo_results_export(
        corpus_id="locomo_conv_43",
        questions_path=qpath,
        stored_rows={
            "locomo_conv_43_q002_c2": _saved_row("locomo_conv_43_q002_c2", "June")
        },
        prediction_key="hiro_answer",
    )

    qa = json.loads(export["content"])[0]["qa"][0]
    assert qa["hiro_answer"] == "June"
    assert "hiro_memory_prediction" not in qa


def test_build_locomo_results_export_requires_sidecar(tmp_path: Path) -> None:
    questions = tmp_path / "locomo_conv_43.questions.yaml"
    questions.write_text(
        "- id: q1\n  question: Q?\n  expected_answer: A\n",
        encoding="utf-8",
    )

    with pytest.raises(LocomoExportError, match="sidecar"):
        build_locomo_results_export(
            corpus_id="locomo_conv_43",
            questions_path=questions,
            stored_rows={"q1": _saved_row("q1", "A")},
        )


# --- evidence recall (read-path metric) ------------------------------------------------------


def _episode_hit(uuid: str, score: float | None = None) -> dict:
    """A recalled RAW EPISODE hit (carries the corpus episode id as its uuid)."""
    hit: dict = {"memory": "raw turn text", "kind": "episode", "uuid": uuid}
    if score is not None:
        hit["score"] = score
    return hit


def test_compute_evidence_recall_matches_fact_and_counts(tmp_path: Path) -> None:
    qpath = _write_locomo_files(tmp_path)
    rows = [
        # q001: a recalled FACT derived from the gold episode → matched via 'fact'.
        _saved_row("locomo_conv_43_q001_c1", "...", "locomo_conv_43_d1_9"),
        # q002: nothing relevant recalled → missed.
        _saved_row("locomo_conv_43_q002_c2", "..."),
    ]
    ev = compute_evidence_recall_map(corpus_id="locomo_conv_43", questions_path=qpath, rows=rows)

    q1 = ev["locomo_conv_43_q001_c1"]
    assert (q1["matched"], q1["total"]) == (1, 1)
    item = q1["items"][0]
    assert item["matched"] is True
    assert item["matched_via"] == "fact"
    assert item["episode_id"] == "locomo_conv_43_d1_9"
    assert item["short_id"] == "d1_9"
    assert item["dia_id"] == "D1:9"

    q2 = ev["locomo_conv_43_q002_c2"]
    assert (q2["matched"], q2["total"]) == (0, 1)
    assert q2["items"][0]["matched"] is False
    assert q2["items"][0]["matched_via"] == ""


def test_compute_evidence_recall_matches_raw_episode_uuid(tmp_path: Path) -> None:
    qpath = _write_locomo_files(tmp_path)
    # The gold episode surfaced as a RAW EPISODE hit (uuid == episode id), not a fact.
    rows = [
        {
            "id": "locomo_conv_43_q002_c2",
            "track": "memory",
            "legs": {"recall": {"recalled": [_episode_hit("locomo_conv_43_d2_1", score=0.7)]}},
        }
    ]
    ev = compute_evidence_recall_map(corpus_id="locomo_conv_43", questions_path=qpath, rows=rows)
    item = ev["locomo_conv_43_q002_c2"]["items"][0]
    assert item["matched"] is True
    assert item["matched_via"] == "episode"
    assert item["score"] == 0.7


def test_compute_evidence_recall_enriches_text_from_episodes_file(tmp_path: Path) -> None:
    qpath = _write_locomo_files(tmp_path)
    # An episodes.jsonl sibling supplies the gold episode's body/speaker/when for the fold.
    (tmp_path / "locomo_conv_43.episodes.jsonl").write_text(
        '{"id": "locomo_conv_43_d1_9", "timestamp": "2023-05-21T19:48:00Z", '
        '"speaker": "John", "body": "My goal is a championship."}\n',
        encoding="utf-8",
    )
    rows = [_saved_row("locomo_conv_43_q001_c1", "...", "locomo_conv_43_d1_9")]
    ev = compute_evidence_recall_map(corpus_id="locomo_conv_43", questions_path=qpath, rows=rows)
    item = ev["locomo_conv_43_q001_c1"]["items"][0]
    assert item["speaker"] == "John"
    assert item["text"] == "My goal is a championship."
    assert item["when"].startswith("2023-05-21")


def test_compute_evidence_recall_no_sidecar_returns_empty(tmp_path: Path) -> None:
    questions = tmp_path / "locomo_conv_43.questions.yaml"
    questions.write_text("- id: q1\n  question: Q?\n  expected_answer: A\n", encoding="utf-8")
    rows = [_saved_row("q1", "A", "locomo_conv_43_d1_9")]
    assert compute_evidence_recall_map(
        corpus_id="locomo_conv_43", questions_path=questions, rows=rows
    ) == {}
