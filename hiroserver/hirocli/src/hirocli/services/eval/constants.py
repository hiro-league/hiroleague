"""Eval Domain-event types.

Streamed by the eval runners (:mod:`hirocli.services.eval.runner_knowledge` /
:mod:`hirocli.services.eval.runner_memory`) so the admin Eval Batch UI updates the
per-question table live without polling — same pattern as the knowledge ingest job
events (one started, progress per item, one completed/failed). They ride the shared
``/knowledge/events`` SSE transport (no separate eval stream — connection budget).
"""

from __future__ import annotations

EVAL_STARTED = "eval.started"
EVAL_SETUP_PROGRESS = "eval.setup_progress"   # ingest / graph-build / remember
EVAL_QUESTION_COMPLETED = "eval.question_completed"
EVAL_COMPLETED = "eval.completed"
EVAL_FAILED = "eval.failed"
# Terminal cancel (user pressed Cancel in the admin Eval panel). Distinct from
# FAILED so the UI reads it as neutral, not an error.
EVAL_CANCELLED = "eval.cancelled"
