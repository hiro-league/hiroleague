"""LoCoMo export helpers for persisted memory-eval results."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

import yaml

from hirocli.services.knowledge.eval_runner import load_questions

_PREDICTION_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LocomoExportError(ValueError):
    """Raised when saved eval rows cannot be rendered as LoCoMo QA results."""


def _sidecar_path(corpus_id: str, questions_path: Path) -> Path:
    candidates = [questions_path.with_name(f"{corpus_id}.locomo.yaml")]
    name = questions_path.name
    if name.endswith(".questions.yaml"):
        candidates.append(questions_path.with_name(f"{name[:-len('.questions.yaml')]}.locomo.yaml"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _safe_int(value: Any, *, field: str, qid: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LocomoExportError(f"{qid}: missing or invalid LoCoMo {field}") from exc


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _context_dia_ids(row: dict[str, Any], episode_to_dia: dict[str, str]) -> list[str]:
    recalled = ((row.get("legs") or {}).get("recall") or {}).get("recalled") or []
    if not isinstance(recalled, list):
        return []
    ids: list[str] = []
    for item in recalled:
        if not isinstance(item, dict):
            continue
        for key in ("chunk_id", "episode_id", "source_episode_id", "uuid"):
            raw = str(item.get(key) or "").strip()
            if raw in episode_to_dia:
                ids.append(episode_to_dia[raw])
                break
    return _dedupe(ids)


def build_locomo_results_export(
    *,
    corpus_id: str,
    questions_path: Path,
    stored_rows: dict[str, dict[str, Any]],
    prediction_key: str = "hiro_memory_prediction",
) -> dict[str, Any]:
    """Build a LoCoMo-compatible QA results JSON file from saved memory eval rows.

    The returned ``content`` is the exact file body intended for LoCoMo's evaluator:
    a top-level list of samples, each containing ``sample_id`` and ``qa``. Counts and
    filename are returned outside that content for the admin UI.
    """

    if not _PREDICTION_KEY_RE.match(prediction_key):
        raise LocomoExportError(
            "prediction_key must be a JSON identifier-like name, e.g. hiro_memory_prediction"
        )
    qpath = Path(questions_path)
    if not qpath.exists():
        raise LocomoExportError(f"Question bank not found: {qpath}")
    sidecar = _sidecar_path(corpus_id, qpath)
    if not sidecar.exists():
        raise LocomoExportError(f"LoCoMo sidecar not found: {sidecar}")
    if not stored_rows:
        raise LocomoExportError(f"No saved eval results found for corpus '{corpus_id}'")

    questions = load_questions(qpath)
    raw_sidecar = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    if not isinstance(raw_sidecar, dict):
        raise LocomoExportError(f"{sidecar}: expected a mapping")

    source = raw_sidecar.get("source") if isinstance(raw_sidecar.get("source"), dict) else {}
    sidecar_questions = raw_sidecar.get("questions")
    if not isinstance(sidecar_questions, dict):
        raise LocomoExportError(f"{sidecar}: missing questions mapping")
    sidecar_episodes = raw_sidecar.get("episodes")
    episode_to_dia = {
        str(eid): str(meta.get("dia_id"))
        for eid, meta in (sidecar_episodes.items() if isinstance(sidecar_episodes, dict) else [])
        if isinstance(meta, dict) and meta.get("dia_id")
    }

    samples: "OrderedDict[str, list[tuple[int, dict[str, Any]]]]" = OrderedDict()
    for bank_index, q in enumerate(questions):
        qid = str(q.get("id") or "")
        row = stored_rows.get(qid)
        if row is None:
            continue
        meta = sidecar_questions.get(qid)
        if not isinstance(meta, dict):
            raise LocomoExportError(f"{qid}: missing LoCoMo sidecar metadata")
        evidence = meta.get("evidence") if isinstance(meta.get("evidence"), dict) else {}
        dia_ids = [str(v) for v in (evidence.get("dia_ids") or [])]
        episode_ids = [str(v) for v in (evidence.get("episode_ids") or [])]
        for episode_id in episode_ids:
            mapped = episode_to_dia.get(episode_id)
            if mapped is not None and mapped not in dia_ids:
                raise LocomoExportError(
                    f"{qid}: evidence episode {episode_id} maps to {mapped}, not listed in dia_ids"
                )

        recall = (row.get("legs") or {}).get("recall") or {}
        answer = recall.get("answer")
        sample_id = str(meta.get("sample_id") or source.get("sample_id") or "")
        if not sample_id:
            raise LocomoExportError(f"{qid}: missing LoCoMo sample_id")
        qa: dict[str, Any] = {
            "question": str(q.get("question") or row.get("question") or ""),
            "answer": str(q.get("expected_answer") or row.get("gold") or ""),
            "category": _safe_int(meta.get("category"), field="category", qid=qid),
            "evidence": dia_ids,
            prediction_key: "" if answer is None else str(answer),
        }
        context = _context_dia_ids(row, episode_to_dia)
        if context:
            qa[f"{prediction_key}_context"] = context

        question_index = _safe_int(
            meta.get("question_index", bank_index), field="question_index", qid=qid
        )
        samples.setdefault(sample_id, []).append((question_index, qa))

    if not samples:
        raise LocomoExportError(f"No saved LoCoMo question rows found for corpus '{corpus_id}'")

    payload = [
        {
            "sample_id": sample_id,
            "qa": [qa for _, qa in sorted(qas, key=lambda item: item[0])],
        }
        for sample_id, qas in samples.items()
    ]
    exported_count = sum(len(sample["qa"]) for sample in payload)
    total_count = len(questions)
    filename = f"{corpus_id}.{prediction_key}.{exported_count}of{total_count}.json"
    return {
        "filename": filename,
        "content": json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        "exported_count": exported_count,
        "total_count": total_count,
        "prediction_key": prediction_key,
        "partial": exported_count < total_count,
    }
