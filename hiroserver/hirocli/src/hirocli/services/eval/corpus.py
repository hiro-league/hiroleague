"""Eval corpus surface — default locations, document tags, question/corpus loading.

Pure-ish discovery layer shared by both runners: where corpora live (knowledge vs the
sibling ``eval-corpus`` repo), the per-corpus document tags, question-bank validation,
and the benchmark-manifest-driven corpus picker. No event/ledger/runner deps.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from hiro_commons.log import Logger

log = Logger.get("SVC.KNOWLEDGE.EVAL")


# Default corpus + questions locations.
#  - MEMORY corpora live in the SIBLING `eval-corpus` repo (hiro-code-reports/eval-corpus): the
#    benchmark manifest + LoCoMo/BEAM/adam/scratch corpora. Resolution: $HIRO_EVAL_CORPUS_DIR, else
#    the sibling clone at ../hiro-code-reports/eval-corpus (same convention as ../hiro-docs).
#  - KNOWLEDGE corpus (l3_synthetic) stays in hiroleague's own `eval/` dir.
# The runner takes these as parameters so tests can point at fixtures; the Tool falls back here.
_REPO_ROOT = Path(__file__).resolve().parents[6]  # services/eval → … → hiroleague repo
_EVAL_CORPUS_ROOT = Path(
    os.environ.get("HIRO_EVAL_CORPUS_DIR") or (_REPO_ROOT.parent / "hiro-code-reports" / "eval-corpus")
)
# Knowledge defaults — hiroleague-local.
DEFAULT_CORPUS_DIR = _REPO_ROOT / "eval" / "l3_synthetic"
DEFAULT_QUESTIONS_FILE = _REPO_ROOT / "eval" / "l3_synthetic.questions.yaml"
# Memory corpus store (admin picker default); any folder can be scanned. Stem convention:
#   <name>.episodes.jsonl ↔ <name>.questions.yaml  (benchmark subfolders via the manifest's `dir`)
DEFAULT_EVAL_FOLDER = _EVAL_CORPUS_ROOT


# Tag auto-applied to ingested eval docs so flat/graph retrieval can be scoped
# to ONLY the synthetic corpus (so the eval comparison stays fair even when the
# workspace has unrelated knowledge docs already ingested). See plan §5f.
#
# Legacy flat tag — matched only the single bundled l3_synthetic corpus. Kept for the
# legacy CLI tool path. The admin route uses the per-corpus tag below.
EVAL_SYNTHETIC_TAG = "_l3_eval_synthetic"

# Per-corpus knowledge-eval tag — the LIVE convention. The admin route tags every ingested
# eval doc with ``_eval_kb_{corpus_id}`` so retrieval AND clear scope to one corpus. Minted
# here (single source) so ingest + clear can't drift onto different tags (the bug that
# stranded orphan eval vectors when the manual clear keyed off the stale flat tag).
EVAL_KB_TAG_PREFIX = "_eval_kb_"


# Memory eval defaults — the bundled Adam turn corpus.
ADAM_CORPUS_FILE = _EVAL_CORPUS_ROOT / "adam_year.episodes.jsonl"
ADAM_QUESTIONS_FILE = _EVAL_CORPUS_ROOT / "adam_year.questions.yaml"

# Default memory-eval set id (the bundled Adam corpus stem) → the ``eval_mem_adam_year`` drawer.
DEFAULT_MEMORY_EVAL_SET = "adam_year"
# Nominal user id for the eval-scoped memory facade. The drawer is minted by the scope
# override (eval_mem_{set}), so this id never reaches a group_id (decision E-a, moot) — a
# negative sentinel keeps it from ever colliding with a real (positive) data.db user id.
MEMORY_EVAL_USER_ID = -1

# Ceiling for the memory track's parallel question phase (the route clamps the request,
# the UI stepper tops out here). Bounded low on purpose: recall's Kuzu queries serialize
# on the shared driver's single AsyncConnection slot regardless, so wider fan-out only
# multiplies concurrent answer/judge LLM calls — i.e. provider rate-limit failures.
MAX_QUESTION_CONCURRENCY = 8


def eval_kb_tag(corpus_id: str) -> str:
    """The per-corpus knowledge-eval document tag (``_eval_kb_{corpus_id}``)."""
    return f"{EVAL_KB_TAG_PREFIX}{corpus_id}"


def load_questions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load + validate the eval questions YAML.

    Each row needs ``id`` + ``question`` and a grading reference — **either** an
    ``expected_answer`` (the ideal answer the LLM judge grades against) **or**
    ``expected_kind: abstain`` (negative control). ``expected_fragments`` is now optional
    (substring scoring was dropped in favor of the judge) but still parsed when present.
    Extra keys (category, requires, notes) pass through."""
    target = path or DEFAULT_QUESTIONS_FILE
    if not target.exists():
        raise FileNotFoundError(f"L3 eval questions not found: {target}")
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{target}: expected a non-empty list of questions")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"{target}: row {i} is not a mapping")
        qid = str(row.get("id") or "").strip()
        qtext = str(row.get("question") or "").strip()
        if not qid or not qtext:
            raise ValueError(f"{target}: row {i} missing id or question")
        # ``expected_kind: abstain`` = negative control (abstaining is the correct outcome).
        expected_kind = str(row.get("expected_kind") or "").strip().lower()
        has_fragments_key = "expected_fragments" in row
        expected = row.get("expected_fragments")
        expected = expected if isinstance(expected, list) else []
        gold = str(row.get("expected_answer") or "").strip()
        # A negative control: explicit abstain, or an explicit empty fragments list with no gold
        # (the legacy "[] = abstain is correct" shorthand).
        negative = expected_kind == "abstain" or (has_fragments_key and not expected and not gold)
        # Grading reference required: a gold answer, a negative control, or legacy fragments.
        if not gold and not expected and not negative:
            raise ValueError(
                f"{target}: row {i} ({qid}): needs an `expected_answer` (judge reference), "
                f"`expected_kind: abstain`, or `expected_fragments`"
            )
        if negative:
            expected_kind = "abstain"
        # requires_graph: explicit bool OR derived from a ``requires`` list that names
        # graph/temporal/world (those categories are where graph/mix should win).
        requires_raw = row.get("requires") or []
        requires_list = requires_raw if isinstance(requires_raw, list) else []
        requires_graph = bool(row.get("requires_graph")) or any(
            str(r).strip().lower() in ("graph", "temporal", "world") for r in requires_list
        )
        out.append(
            {
                "id": qid,
                "category": str(row.get("category") or ""),
                "subcategory": str(row.get("subcategory") or ""),
                # Authored difficulty (medium/hard/very_hard). Optional — corpora without it
                # fall into the "unspecified" bucket in the by_difficulty report. Reporting-only.
                "difficulty": str(row.get("difficulty") or "").strip().lower(),
                "question": qtext,
                "expected_fragments": [str(f) for f in expected],
                "requires_graph": requires_graph,
                # The ideal answer the LLM judge grades against (shown as "Ideal" in results).
                "expected_answer": gold,
                # "abstain" ⇒ negative control: abstaining is the correct outcome.
                "expected_kind": expected_kind,
            }
        )
    return out


def load_adam_questions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the Adam question bank (same validation as ``load_questions``)."""
    return load_questions(path or ADAM_QUESTIONS_FILE)


# ---------------------------------------------------------------------------
# Corpus discovery — scan a folder, pair corpuses with their question banks
# ---------------------------------------------------------------------------
#
# A corpus is identified by (track, folder, id). Stem convention (docs §12):
#   memory:    <id>.episodes.jsonl    ↔ <id>.questions.yaml
#   knowledge: <id>/ (folder of .md)  ↔ <id>.questions.yaml (sibling of the folder)
# id doubles as the eval drawer suffix → eval_mem_<id> / eval_kb_<id>.


def _safe_question_count(questions_path: Path) -> int:
    """Best-effort question count for the picker; 0 when the bank is missing/unreadable."""
    if not questions_path.exists():
        return 0
    try:
        return len(load_questions(questions_path))
    except Exception:
        # A malformed bank shouldn't break corpus discovery — surface 0 and let the run
        # fail loud later if the user picks it.
        log.warning("⚠️ knowledge.eval — unreadable question bank · path=%s", questions_path, exc_info=True)
        return 0


# reason: memory-track corpuses are grouped into named benchmarks via this manifest. It is the
# single source of truth for which corpuses the picker lists, their grouping, order, and labels
# (no hardcoding) — bare corpus files not listed here are intentionally hidden (legacy scratch
# corpora). The knowledge track does NOT use the manifest (it still scans every doc folder).
BENCHMARK_MANIFEST_NAME = "benchmarks.yaml"


def _load_benchmark_manifest(folder: Path) -> list[dict[str, Any]]:
    """Load ``benchmarks.yaml`` → ordered list of ``{id, label, corpuses: [{id, label}]}``.

    Returns ``[]`` when the manifest is missing or unreadable; memory-track discovery then
    lists nothing — a loud-enough signal the manifest needs attention without crashing the
    picker. Each benchmark: ``{id, label, dir, corpuses}`` where ``dir`` is an optional
    subfolder (relative to the corpus root) the benchmark's files live in (e.g. ``beam128k``),
    ``""`` = flat at the root. Corpus entries may be a bare id (string) or a ``{id, label}`` map."""
    manifest_path = folder / BENCHMARK_MANIFEST_NAME
    if not manifest_path.exists():
        log.warning("⚠️ knowledge.eval — benchmark manifest missing · path=%s", manifest_path)
        return []
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception:
        log.warning("⚠️ knowledge.eval — unreadable benchmark manifest · path=%s", manifest_path, exc_info=True)
        return []
    out: list[dict[str, Any]] = []
    for bid, body in (raw.get("benchmarks") or {}).items():
        body = body or {}
        corpuses: list[dict[str, str]] = []
        for entry in body.get("corpuses") or []:
            if isinstance(entry, str):
                corpuses.append({"id": entry, "label": entry})
            elif isinstance(entry, dict) and entry.get("id"):
                corpuses.append({"id": str(entry["id"]), "label": str(entry.get("label") or entry["id"])})
        out.append(
            {
                "id": str(bid),
                "label": str(body.get("label") or bid),
                "dir": str(body.get("dir") or ""),
                "corpuses": corpuses,
            }
        )
    return out


def _memory_corpus_entry(base: Path, stem: str) -> dict[str, Any] | None:
    """Build a memory-track picker entry for ``stem`` (``<stem>.episodes.jsonl``), or ``None``
    when its episodes file is absent — a manifest-listed corpus whose data hasn't landed yet
    (e.g. an empty benchmark) is skipped rather than surfaced as a broken option."""
    f = base / f"{stem}.episodes.jsonl"
    if not f.exists():
        return None
    qpath = base / f"{stem}.questions.yaml"
    episodes = 0
    try:
        from hirocli.services.knowledge.graph.graphiti_corpus import load_episodes_file

        episodes = len(load_episodes_file(f))
    except Exception:
        log.warning("⚠️ knowledge.eval — unreadable corpus · path=%s", f, exc_info=True)
    return {
        "id": stem,
        "name": stem,
        "corpus_path": str(f),
        "questions_path": str(qpath) if qpath.exists() else "",
        "question_count": _safe_question_count(qpath),
        "item_count": episodes,
    }


def discover_corpuses(folder: Path | str, track: str) -> list[dict[str, Any]]:
    """List the corpuses in ``folder`` for ``track`` (``memory`` | ``knowledge``).

    Each entry: ``{id, name, corpus_path, questions_path, question_count, item_count}``;
    memory entries also carry ``{label, benchmark, benchmark_label}`` from the benchmark
    manifest. ``item_count`` is episodes (memory) or ``.md`` docs (knowledge). Returns ``[]``
    for a missing/empty folder (the picker shows a hint, not an error).

    Memory track is **manifest-driven**: only corpuses listed under a benchmark in
    ``benchmarks.yaml`` appear, in manifest order, grouped + labeled by benchmark. The
    knowledge track is unchanged — it still scans every ``.md`` doc folder directly."""
    base = Path(folder)
    if not base.exists() or not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    if track == "memory":
        for bench in _load_benchmark_manifest(base):
            # A benchmark's files may live in a subfolder (manifest `dir:`, e.g. beam128k/) or
            # flat at the root (`dir` == "", e.g. locomo); resolve each corpus against that base.
            bench_base = base / bench["dir"] if bench["dir"] else base
            for corp in bench["corpuses"]:
                entry = _memory_corpus_entry(bench_base, corp["id"])
                if entry is None:
                    continue
                entry["label"] = corp["label"]
                entry["benchmark"] = bench["id"]
                entry["benchmark_label"] = bench["label"]
                out.append(entry)
    else:  # knowledge — a corpus is a subfolder of .md docs
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            md = list(d.glob("*.md"))
            if not md:
                continue
            qpath = base / f"{d.name}.questions.yaml"
            out.append(
                {
                    "id": d.name,
                    "name": d.name,
                    "corpus_path": str(d),
                    "questions_path": str(qpath) if qpath.exists() else "",
                    "question_count": _safe_question_count(qpath),
                    "item_count": len(md),
                }
            )
    return out
