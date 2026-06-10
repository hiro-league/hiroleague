from __future__ import annotations

import json
from pathlib import Path

import pytest

from hirocli.services.knowledge.eval_locomo import (
    LocomoExportError,
    build_locomo_results_export,
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
