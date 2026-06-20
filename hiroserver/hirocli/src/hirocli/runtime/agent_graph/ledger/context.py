"""ContextVar bridge for the active ledger entry, run accumulator, and sub-step scope."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import LedgerEntry, RunAccumulator

current_entry: ContextVar["LedgerEntry | None"] = ContextVar(
    "graph_ledger_entry",
    default=None,
)
current_run: ContextVar["RunAccumulator | None"] = ContextVar(
    "graph_ledger_run",
    default=None,
)
# Set by a parent node around a nested subgraph invoke (e.g. chat ``knowledge_retrieve`` running the
# retrieval subgraph) so the nested ``knowledge/*`` rows render as sub-steps of the parent (``4.1``,
# ``4.2`` …) instead of restarting their own step counter. Carries the parent's ``step_index``.
current_substep: ContextVar[int | None] = ContextVar(
    "graph_ledger_substep",
    default=None,
)
