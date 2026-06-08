"""LangSmith trace spans tied to the ledger run-id convention.

Eval and ingestion make many LLM calls **outside** any LangGraph graph: Graphiti's
internal extraction/dedup/dating during ``add_episode``, plus the eval answer/judge
steps. With no enclosing run each call lands in LangSmith as its own root, so a whole
eval (or one ``add_episode``) reads as dozens of scattered traces instead of one tree.

:func:`traced_run` opens an **ambient** LangSmith span. Nested LangChain/LLM calls
attach to it automatically via contextvars (LangChain reads the current LangSmith run
tree), so callers don't thread a ``RunnableConfig`` through Graphiti (which won't accept
one) — they just wrap the scope. The result is the hierarchy:

    knowledge_eval / memory_eval          (root, run_id = uuid5(eval run id))
    ├── graph_ingest                      (one per add_episode batch)
    │   └── add_episode                   (Graphiti's LLM calls nest here)
    └── eval_question                     (answer legs + judge nest here)

Everything is a **no-op** when LangSmith tracing is disabled or the package is absent,
so callers wrap unconditionally and pay nothing when tracing is off.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from hiro_commons.log import Logger

log = Logger.get("RUNTIME.TRACING")


def langsmith_run_id(ledger_run_id: str) -> uuid.UUID:
    """Deterministic LangSmith run id for a ledger ``run_id``.

    ``UUID5(NAMESPACE_URL, ledger_run_id)`` — the single convention shared by the chat
    agent's ``RunnableConfig``, the knowledge-answer config, ``langsmith_url_for_run``,
    and the eval/ingest spans here, so a ledger run and its LangSmith trace always
    resolve to the same id (the admin "open in LangSmith" link keeps working)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, ledger_run_id)


def _tracing_enabled() -> bool:
    """True when LangSmith tracing is active (env or ``tracing_context``).

    Defers to LangSmith's own check so we honor exactly the same switches the SDK does
    (``LANGSMITH_TRACING`` / ``LANGCHAIN_TRACING_V2``). Any import/attr error ⇒ off."""
    try:
        from langsmith.utils import tracing_is_enabled
    except Exception:
        return False
    try:
        return bool(tracing_is_enabled())
    except Exception:
        # A misconfigured tracing context must never break the caller — treat as off.
        log.debug("langsmith tracing_is_enabled() raised; treating tracing as off", exc_info=True)
        return False


@contextlib.contextmanager
def traced_run(
    name: str,
    *,
    ledger_run_id: str | None = None,
    run_type: str = "chain",
    tags: Sequence[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> Iterator[Any]:
    """Open a LangSmith span that nested LangChain/LLM calls attach to.

    ``ledger_run_id`` (when given) fixes the span's run id to
    ``langsmith_run_id(ledger_run_id)`` so the run is findable via the same id the CSV
    ledger uses. Pass it only on the **outermost** span of a unit of work (eval root,
    standalone ingest); inner spans omit it and simply nest.

    Yields the LangSmith ``RunTree`` (for adding outputs/metadata), or ``None`` when
    tracing is off / unavailable. Body exceptions propagate (LangSmith records the span
    as errored); tracing setup never raises into the caller."""
    if not _tracing_enabled():
        yield None
        return
    try:
        from langsmith import trace
    except ImportError:
        log.debug("langsmith package not installed; skipping trace span '%s'", name)
        yield None
        return
    run_id = langsmith_run_id(ledger_run_id) if ledger_run_id else None
    with trace(
        name,
        run_type=run_type,
        run_id=run_id,
        tags=[t for t in tags if t] if tags else None,
        metadata=dict(metadata) if metadata else None,
        inputs=dict(inputs) if inputs else None,
    ) as run_tree:
        yield run_tree


__all__ = ["langsmith_run_id", "traced_run"]
