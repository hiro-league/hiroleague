"""LoCoMo export helpers + per-question evidence-recall metric for persisted memory-eval results."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from hiro_commons.log import Logger

from hirocli.services.eval.corpus import load_questions

log = Logger.get("SVC.KNOWLEDGE.EVAL.LOCOMO")

_PREDICTION_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Keys on a recalled item that can carry its SOURCE episode id, in priority order: a fact links to
# its origin episode via chunk_id/source, while a raw episode hit carries the episode id as its own
# uuid. Shared by the LoCoMo export (recalled → dia-id) and the evidence-recall metric (recalled →
# episode-id) so both decide "was this gold episode recalled?" identically (the LoCoMo calculation).
_EPISODE_LINK_KEYS = ("chunk_id", "episode_id", "source_episode_id", "uuid")


class LocomoExportError(ValueError):
    """Raised when saved eval rows cannot be rendered as LoCoMo QA results."""


def _sidecar_path(corpus_id: str, questions_path: Path) -> Path:
    candidates = [questions_path.with_name(f"{corpus_id}.locomo.yaml")]
    name = questions_path.name
    stem = name[: -len(".questions.yaml")] if name.endswith(".questions.yaml") else None
    if stem is not None:
        candidates.append(questions_path.with_name(f"{stem}.locomo.yaml"))
    # BEAM corpora ship the same-schema sidecar (questions[*].evidence.episode_ids +
    # episodes[*].dia_id) as `<stem>.beam.yaml`; accept it too so evidence-recall works for
    # BEAM, not only LoCoMo. (Default fallback stays `.locomo.yaml` for the LoCoMo export path.)
    candidates.append(questions_path.with_name(f"{corpus_id}.beam.yaml"))
    if stem is not None:
        candidates.append(questions_path.with_name(f"{stem}.beam.yaml"))
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


def _recalled_episode_id(item: Any, valid_ids: "set[str]") -> str | None:
    """The corpus episode id a recalled item came from — its first link key (see
    ``_EPISODE_LINK_KEYS``) that names a real corpus episode — or ``None``. ``valid_ids`` guards
    against a non-episode uuid (a fact/entity graph uuid) coincidentally being treated as one."""
    if not isinstance(item, dict):
        return None
    for key in _EPISODE_LINK_KEYS:
        raw = str(item.get(key) or "").strip()
        if raw and raw in valid_ids:
            return raw
    return None


def _context_dia_ids(row: dict[str, Any], episode_to_dia: dict[str, str]) -> list[str]:
    recalled = ((row.get("legs") or {}).get("recall") or {}).get("recalled") or []
    if not isinstance(recalled, list):
        return []
    valid_ids = set(episode_to_dia)
    ids: list[str] = []
    for item in recalled:
        eid = _recalled_episode_id(item, valid_ids)
        if eid is not None:
            ids.append(episode_to_dia[eid])
    return _dedupe(ids)


def _short_episode_id(episode_id: str, corpus_id: str) -> str:
    """Trim the corpus prefix for compact display (``locomo_conv_43_d6_15`` → ``d6_15``)."""
    prefix = f"{corpus_id}_"
    return episode_id[len(prefix):] if episode_id.startswith(prefix) else episode_id


def _episodes_path(corpus_id: str, questions_path: Path) -> Path:
    """Sibling ``*.episodes.jsonl`` for a corpus, mirroring ``_sidecar_path`` discovery."""
    candidates = [questions_path.with_name(f"{corpus_id}.episodes.jsonl")]
    name = questions_path.name
    if name.endswith(".questions.yaml"):
        candidates.append(
            questions_path.with_name(f"{name[:-len('.questions.yaml')]}.episodes.jsonl")
        )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_episode_bodies(corpus_id: str, questions_path: Path) -> dict[str, dict[str, str]]:
    """``{episode_id: {speaker, text, when}}`` from the corpus episodes.jsonl, for evidence display.

    Best-effort text enrichment only: a missing/unreadable/invalid episodes file degrades the
    evidence section to ids-without-text rather than breaking the results read, so it is logged and
    swallowed (not raised)."""
    path = _episodes_path(corpus_id, questions_path)
    if not path.exists():
        return {}
    # Lazy import: parse_episodes_jsonl pulls in graphiti_core; keep it off eval_locomo's import path.
    from hirocli.services.knowledge.graph.graphiti_corpus import parse_episodes_jsonl

    try:
        episodes = parse_episodes_jsonl(
            path.read_text(encoding="utf-8"), default_document_id=corpus_id
        )
    except (OSError, ValueError):
        log.warning(
            "⚠️ knowledge.eval — evidence episode bodies unreadable · corpus=%s · path=%s",
            corpus_id,
            path,
            exc_info=True,
        )
        return {}
    bodies: dict[str, dict[str, str]] = {}
    for ep in episodes:
        when = ep.reference_time.isoformat() if ep.reference_time else ""
        bodies[ep.chunk_id] = {"speaker": ep.speaker or "", "text": ep.text or "", "when": when}
    return bodies


@dataclass(frozen=True)
class EvidenceRecallContext:
    """Pre-loaded LoCoMo sidecar state for scoring per-question evidence recall.

    Built ONCE (``load_evidence_recall_context``) so a run can score each question's evidence
    recall the moment it completes — emitting it live on ``question_completed`` instead of only
    on the post-run read path. ``compute_evidence_recall_map`` (the bulk read-path enrichment)
    is now a thin wrapper over this. Holds the gold-evidence episode ids per question, the
    episode→dia-id map, the episode bodies (best-effort text), and the valid-id guard set."""

    corpus_id: str
    gold_by_q: dict[str, list[str]]
    episode_to_dia: dict[str, str]
    bodies: dict[str, dict[str, str]]
    valid_ids: set[str]

    def for_recalled(self, qid: str, recalled: Any) -> dict[str, Any] | None:
        """Evidence recall for ONE question's recalled context: ``{matched, total, items}``,
        matched the SAME way as the LoCoMo export (``_recalled_episode_id``) so a gold turn counts
        whether it surfaced as a raw episode or a fact/entity derived from it. ``None`` when this
        question has no gold evidence (a non-LoCoMo question), so the caller leaves the column blank."""
        gold = self.gold_by_q.get(str(qid))
        if not gold:
            return None
        gold_set = set(gold)
        # eid → (kind, score) of the best (highest-scoring) recalled item that covers it.
        best: dict[str, tuple[str, float | None]] = {}
        if isinstance(recalled, list):
            for item in recalled:
                eid = _recalled_episode_id(item, self.valid_ids)
                if eid is None or eid not in gold_set:
                    continue
                kind = str((item.get("kind") if isinstance(item, dict) else "") or "fact")
                raw_score = item.get("score") if isinstance(item, dict) else None
                score = float(raw_score) if isinstance(raw_score, (int, float)) else None
                prev = best.get(eid)
                if prev is None or (score if score is not None else -1.0) > (
                    prev[1] if prev[1] is not None else -1.0
                ):
                    best[eid] = (kind, score)
        items: list[dict[str, Any]] = []
        for eid in gold:
            body = self.bodies.get(eid, {})
            match = best.get(eid)
            items.append(
                {
                    "episode_id": eid,
                    "short_id": _short_episode_id(eid, self.corpus_id),
                    "dia_id": self.episode_to_dia.get(eid, ""),
                    "speaker": body.get("speaker", ""),
                    "text": body.get("text", ""),
                    "when": body.get("when", ""),
                    "matched": match is not None,
                    "matched_via": match[0] if match else "",
                    "score": match[1] if match else None,
                }
            )
        return {
            "matched": sum(1 for it in items if it["matched"]),
            "total": len(items),
            "items": items,
        }


def load_evidence_recall_context(
    corpus_id: str, questions_path: Path
) -> EvidenceRecallContext | None:
    """Load the LoCoMo sidecar + episode bodies once for ``corpus_id`` so per-question evidence
    recall can be scored live (and in bulk on the read path). ``None`` for a corpus with no sidecar
    (non-LoCoMo) or a sidecar that lists no gold evidence — callers then skip evidence recall."""
    sidecar = _sidecar_path(corpus_id, questions_path)
    if not sidecar.exists():
        return None
    try:
        raw_sidecar = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        log.warning(
            "⚠️ knowledge.eval — evidence sidecar unreadable · corpus=%s · path=%s",
            corpus_id,
            sidecar,
            exc_info=True,
        )
        return None
    if not isinstance(raw_sidecar, dict):
        return None
    sidecar_questions = raw_sidecar.get("questions")
    if not isinstance(sidecar_questions, dict):
        return None
    sidecar_episodes = raw_sidecar.get("episodes")
    episode_to_dia = {
        str(eid): str(meta.get("dia_id"))
        for eid, meta in (sidecar_episodes.items() if isinstance(sidecar_episodes, dict) else [])
        if isinstance(meta, dict) and meta.get("dia_id")
    }

    # Gold evidence episode ids per question (in sidecar order, for stable display).
    gold_by_q: dict[str, list[str]] = {}
    all_gold: set[str] = set()
    for qid, meta in sidecar_questions.items():
        if not isinstance(meta, dict):
            continue
        evidence = meta.get("evidence") if isinstance(meta.get("evidence"), dict) else {}
        episode_ids = [str(v) for v in (evidence.get("episode_ids") or []) if str(v).strip()]
        if episode_ids:
            gold_by_q[str(qid)] = episode_ids
            all_gold.update(episode_ids)
    if not gold_by_q:
        return None

    bodies = _load_episode_bodies(corpus_id, questions_path)
    # Validity guard for episode-id matching: every id the corpus actually knows about.
    valid_ids = set(episode_to_dia) | all_gold | set(bodies)
    return EvidenceRecallContext(
        corpus_id=corpus_id,
        gold_by_q=gold_by_q,
        episode_to_dia=episode_to_dia,
        bodies=bodies,
        valid_ids=valid_ids,
    )


def compute_evidence_recall_map(
    *,
    corpus_id: str,
    questions_path: Path,
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Per-question evidence recall: for each question whose LoCoMo sidecar lists gold evidence
    episodes, how many of those episodes the recalled context covered — matched the SAME way as the
    LoCoMo export (``_recalled_episode_id``), so a gold turn counts whether it surfaced as a raw
    episode or as a fact/entity derived from it.

    Returns ``{qid: {matched, total, items}}`` where each item carries the episode id (+ short id /
    dia id), the episode text/speaker/when (best-effort), and whether/how it matched (kind + score).
    Returns ``{}`` for corpora without a sidecar (non-LoCoMo). Pure read-path enrichment — does not
    touch persisted rows. The live runner uses ``EvidenceRecallContext.for_recalled`` directly so it
    can emit the same value per question as it completes."""
    ctx = load_evidence_recall_context(corpus_id, questions_path)
    if ctx is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        qid = str(row.get("id") or "")
        recalled = ((row.get("legs") or {}).get("recall") or {}).get("recalled") or []
        ev = ctx.for_recalled(qid, recalled)
        if ev is not None:
            out[qid] = ev
    return out


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
