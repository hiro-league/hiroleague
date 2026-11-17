"""Transparent observer for graphiti's NON-LLM entity dedup auto-merges.

The LLM ingest stages route through :class:`GraphitiLLMClient`, so they're captured
directly. But graphiti also auto-merges freshly-extracted entities **without an LLM** —
exact normalized-name hits and fuzzy MinHash/LSH matches in
``dedup_helpers._resolve_with_similarity`` — and those never touch our adapter, so they
would be invisible in the ingest trace (you'd see "resolve entities" with fewer items and
no explanation of where the missing ones went).

This module wraps that one function with a **pass-through**: graphiti still performs the
real resolution (we never reimplement the write path); we only read the resulting
``duplicate_pairs`` and record each auto-merge as a ``dedup_entities_auto`` stage when an
ingest capture is active. The wrapper is a strict no-op when no capture is set, so it's
safe to install **process-wide once** — every other graphiti caller is unaffected.

Pinned to the validated graphiti layout (signature probe) so a drift fails loud rather
than silently recording wrong merges; engagement degrades gracefully (a compat failure
logs and skips dedup observation — the LLM stages are still captured, and ingestion, a
WRITE path, is never broken)."""

from __future__ import annotations

import inspect
from typing import Any

from hiro_commons.log import Logger

from .ingest_trace import IngestStageRecord, current_ingest_capture, stage_label
from .retrieval_trace import _node_brief

log = Logger.get("SVC.KNOWLEDGE.GRAPH.DEDUP_TRACE")

_DEDUP_NODE = "dedup_entities_auto"

# The leading params we depend on for the wrapped graphiti internal. A rename/reorder
# trips the guard (the observer reads positional args + ``state.duplicate_pairs``).
_EXPECTED_RESOLVE_PARAMS = ["extracted_nodes", "indexes", "state"]

_installed = False
_original: Any = None


class GraphitiDedupCompatError(RuntimeError):
    """Raised when graphiti's dedup internals no longer match the observer's pin."""


def _assert_dedup_compatible() -> None:
    """Fail loud unless the wrapped dedup internal matches the validated layout."""
    from graphiti_core.utils.maintenance import node_operations as nops
    from graphiti_core.utils.maintenance.dedup_helpers import DedupResolutionState

    from .graphiti_compat import PINNED_GRAPHITI_VERSION

    fn = getattr(nops, "_resolve_with_similarity", None)
    if fn is None:
        raise GraphitiDedupCompatError(
            f"graphiti-core {PINNED_GRAPHITI_VERSION}: node_operations._resolve_with_similarity "
            f"is missing — the ingest dedup observer depends on it."
        )
    params = list(inspect.signature(fn).parameters)
    if params[: len(_EXPECTED_RESOLVE_PARAMS)] != _EXPECTED_RESOLVE_PARAMS:
        raise GraphitiDedupCompatError(
            f"graphiti-core {PINNED_GRAPHITI_VERSION}: _resolve_with_similarity signature changed "
            f"(expected leading {_EXPECTED_RESOLVE_PARAMS}, got {params}). Re-validate the ingest "
            f"dedup observer (graphiti_dedup_trace)."
        )
    if "duplicate_pairs" not in getattr(DedupResolutionState, "__dataclass_fields__", {}):
        raise GraphitiDedupCompatError(
            f"graphiti-core {PINNED_GRAPHITI_VERSION}: DedupResolutionState.duplicate_pairs is "
            f"missing — the ingest dedup observer reads it. Re-validate graphiti_dedup_trace."
        )


def _dedup_stage(extracted: Any, matched: Any) -> IngestStageRecord:
    """One auto-merge → a render-ready ``dedup_entities_auto`` stage.

    ``input`` is the freshly-extracted entity; ``output`` is the existing entity it was
    merged into (both projected with the shared node brief), so the dialog shows exactly
    which entity collapsed into which — the dedup the LLM never saw."""
    return IngestStageRecord(
        node=_DEDUP_NODE,
        label=stage_label(_DEDUP_NODE),
        operation="dedup_similarity",
        source="dedup",
        meta={"method": "exact/fuzzy (deterministic)"},
        input=_node_brief(extracted),
        output={
            "merged_into": _node_brief(matched),
            "decision": "auto-merge — no LLM (exact name or fuzzy MinHash ≥ threshold)",
        },
    )


def install_dedup_trace() -> bool:
    """Install the pass-through observer once (idempotent). Returns True if active.

    Best-effort: a compat failure logs and returns False (the LLM stages are still
    captured; ingestion is never broken). Safe to install permanently — the wrapper only
    OBSERVES, and no-ops whenever no ingest capture is engaged."""
    global _installed, _original
    if _installed:
        return True
    try:
        _assert_dedup_compatible()
    except Exception:
        log.warning(
            "⚠️ graphiti — non-LLM dedup trace NOT installed (compat drift); "
            "LLM stages still captured",
            exc_info=True,
        )
        return False

    from graphiti_core.utils.maintenance import node_operations as nops

    _original = nops._resolve_with_similarity

    def _traced_resolve_with_similarity(extracted_nodes: Any, indexes: Any, state: Any) -> None:
        # Snapshot before so we record only the pairs THIS call added (works whether
        # graphiti calls it per-node with a fresh state or in a batch).
        before = len(getattr(state, "duplicate_pairs", None) or [])
        _original(extracted_nodes, indexes, state)
        capture = current_ingest_capture.get()
        if capture is None:
            return  # transparent: no capture → behaves exactly like the original
        try:
            pairs = getattr(state, "duplicate_pairs", None) or []
            for extracted, matched in pairs[before:]:
                capture.add_stage(_dedup_stage(extracted, matched))
        except Exception:
            # Observation must never break ingestion (a WRITE path).
            log.warning("⚠️ graphiti.dedup — auto-merge trace capture failed", exc_info=True)

    nops._resolve_with_similarity = _traced_resolve_with_similarity
    _installed = True
    log.info("✅ graphiti — non-LLM dedup trace observer installed (pass-through)")
    return True


__all__ = ["GraphitiDedupCompatError", "install_dedup_trace"]
