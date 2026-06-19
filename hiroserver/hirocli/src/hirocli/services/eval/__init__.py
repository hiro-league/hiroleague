"""Eval feature — memory + knowledge retrieval evaluation.

A peer of the ``memory`` and ``knowledge`` services (formerly nested under
``services/knowledge/eval_*``). Two runners share one corpus/model/summary/event
core: :func:`run_eval` (knowledge: flat/graphiti legs + PROCEED/PIVOT gate) and
:func:`run_memory_eval` (memory: single recall leg, persisted per-corpus results).
"""

from __future__ import annotations

from hirocli.services.eval.runner import *  # noqa: F401,F403  (stable public surface)
