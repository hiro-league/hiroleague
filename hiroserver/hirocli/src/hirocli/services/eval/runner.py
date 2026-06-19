"""Eval runner — re-export surface over the split implementation modules.

The runner was decomposed (initial-dev mode, no back-compat) into focused modules:

* :mod:`hirocli.services.eval.corpus` — corpus/question loading, defaults, tags
* :mod:`hirocli.services.eval.models` — result dataclasses, leg modes, eval model builders
* :mod:`hirocli.services.eval.summary` — per-mark/field breakdowns + gate verdict
* :mod:`hirocli.services.eval.events` — Domain-event publish + cooperative cancel
* :mod:`hirocli.services.eval.runner_knowledge` — :func:`run_eval` (flat/graphiti legs)
* :mod:`hirocli.services.eval.runner_memory` — :func:`run_memory_eval` (recall leg)

This module keeps the historical ``services.eval.runner`` import path stable. New code
should import from the owning submodule (or the :mod:`hirocli.services.eval` package).

Event types published (see ``knowledge/constants.py``):

* ``eval.started`` — once, at the start, with run_id + total_questions
* ``eval.setup_progress`` — during setup (ingest synthetic / build graph / remember)
* ``eval.question_completed`` — once per question
* ``eval.completed`` — once, with summary + gate verdict
* ``eval.failed`` — once on uncaught exception (run aborted)
"""

from __future__ import annotations

from hirocli.services.eval.corpus import (
    ADAM_CORPUS_FILE,
    ADAM_QUESTIONS_FILE,
    BENCHMARK_MANIFEST_NAME,
    DEFAULT_CORPUS_DIR,
    DEFAULT_EVAL_FOLDER,
    DEFAULT_MEMORY_EVAL_SET,
    DEFAULT_QUESTIONS_FILE,
    EVAL_KB_TAG_PREFIX,
    EVAL_SYNTHETIC_TAG,
    MAX_QUESTION_CONCURRENCY,
    MEMORY_EVAL_USER_ID,
    _load_benchmark_manifest,
    _memory_corpus_entry,
    _safe_question_count,
    discover_corpuses,
    eval_kb_tag,
    load_adam_questions,
    load_questions,
)
from hirocli.services.eval.events import (
    _cancel_requested,
    _preview,
    _publish,
    _raise_if_cancelled,
)
from hirocli.services.eval.models import (
    ALL_EVAL_MODES,
    DEFAULT_EVAL_MODES,
    EvalSummary,
    LegResult,
    QuestionResult,
    _build_eval_model,
    build_eval_answer_model,
    build_eval_judge_model,
    normalize_modes,
)
from hirocli.services.eval.runner_knowledge import (
    _run_one_question,
    clear_eval_data,
    collect_eval_doc_ids,
    collect_synthetic_doc_ids,
    ingest_synthetic_corpus_via_service,
    run_eval,
)
from hirocli.services.eval.runner_memory import (
    _CancelRequestedInQuestion,
    _memory_question,
    _memory_question_task,
    _record_ingested_range,
    _remember_episodes,
    _reset_ingested_ranges,
    _unwrap_question_failure,
    run_memory_eval,
)
from hirocli.services.eval.summary import (
    _MARK_GROUPS,
    _MARK_TO_GROUP,
    _best_graph_delta_marks,
    _empty_breakdown_bucket,
    _memory_recall_leg,
    _summarize,
    _tally_leg,
    field_breakdown,
    field_breakdown_rows,
    summarize_memory_rows,
)

__all__ = [
    "ADAM_CORPUS_FILE",
    "ADAM_QUESTIONS_FILE",
    "ALL_EVAL_MODES",
    "DEFAULT_CORPUS_DIR",
    "DEFAULT_EVAL_FOLDER",
    "DEFAULT_EVAL_MODES",
    "DEFAULT_MEMORY_EVAL_SET",
    "DEFAULT_QUESTIONS_FILE",
    "EVAL_SYNTHETIC_TAG",
    "EVAL_KB_TAG_PREFIX",
    "eval_kb_tag",
    "MAX_QUESTION_CONCURRENCY",
    "MEMORY_EVAL_USER_ID",
    "discover_corpuses",
    "EvalSummary",
    "LegResult",
    "QuestionResult",
    "build_eval_answer_model",
    "build_eval_judge_model",
    "field_breakdown",
    "field_breakdown_rows",
    "summarize_memory_rows",
    "clear_eval_data",
    "collect_eval_doc_ids",
    "collect_synthetic_doc_ids",
    "ingest_synthetic_corpus_via_service",
    "load_adam_questions",
    "load_questions",
    "normalize_modes",
    "run_eval",
    "run_memory_eval",
]
