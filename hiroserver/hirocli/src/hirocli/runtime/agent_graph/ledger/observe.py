"""Node-facing ledger API — ``observe()``, sub-step scope, child rows."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from .context import current_entry, current_substep


def observe(
    *,
    input: str | None = None,
    output: str | None = None,
    decision: str | tuple[str, str] | None = None,
    usage: dict | None = None,
    skipped: str | None = None,
    error: str | None = None,
    fail: dict | None = None,
    input_max_len: int = 280,
    output_max_len: int = 280,
) -> None:
    """Declarative ledger write for the current node. No-op without an active entry."""
    entry = current_entry.get()
    if entry is None:
        return
    if input is not None:
        entry.set_input_preview(input, max_len=input_max_len)
    if usage is not None:
        entry.add_usage(**usage)
    if decision is not None:
        kind, detail = decision if isinstance(decision, tuple) else (decision, "")
        entry.set_decision(kind, detail)
    if skipped is not None:
        entry.set_skipped(skipped)
    if error is not None:
        entry.set_error(error)
    if output is not None:
        entry.set_output_preview(output, max_len=output_max_len)
    if fail is not None:
        entry.fail(
            fail["code"],
            message=fail.get("message", ""),
            decision=fail.get("decision", "provider_error"),
        )


@contextmanager
def substep_scope():
    """Nest child rows (subgraph / ingest) under the current node's step. No-op without entry."""
    entry = current_entry.get()
    token = current_substep.set(entry.step_index) if entry is not None else None
    try:
        yield
    finally:
        if token is not None:
            current_substep.reset(token)


def record_child(
    *,
    node: str,
    status: str = "ok",
    elapsed_ms: int = 0,
    branch_index: int | None = None,
    input: str | None = None,
    output: str | None = None,
    decision: str | tuple[str, str] | None = None,
    usage: dict | None = None,
    fail: dict | None = None,
) -> None:
    """Spawn + fill one child ledger row under the current entry. No-op without entry."""
    parent = current_entry.get()
    if parent is None:
        return
    child = parent.spawn_child(
        node=node,
        status=status,
        elapsed_ms=elapsed_ms,
        branch_index=branch_index,
    )
    if input is not None:
        child.set_input_preview(input)
    if output is not None:
        child.set_output_preview(output)
    if usage is not None:
        child.add_usage(**usage)
    if decision is not None:
        kind, detail = decision if isinstance(decision, tuple) else (decision, "")
        child.set_decision(kind, detail)
    if fail is not None:
        child.fail(
            fail["code"],
            message=fail.get("message", ""),
            decision=fail.get("decision", "provider_error"),
        )
