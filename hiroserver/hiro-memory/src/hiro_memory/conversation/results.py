"""What one conversation-memory write returns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryUsage:
    """Aggregated LLM usage for one memory write operation."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    call_count: int


@dataclass(frozen=True)
class MemoryAddResult:
    """Outcome of a single :meth:`MemoryService.add` call.

    ``stored_count`` is how many memories the backend actually stored this turn
    (mem0: vector rows written; Graphiti: facts learned). ``usage`` may be ``None``
    when token accounting is owned elsewhere (e.g. the Graph-Runs ledger for the
    Graphiti backend). These types are the *contract's* result types, so they live in
    the domain layer — every backend (mem0, Graphiti) returns them."""

    usage: MemoryUsage | None
    stored_count: int
    stored_items: tuple[dict[str, Any], ...] = ()

