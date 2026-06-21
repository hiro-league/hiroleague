"""``NodeOutcome`` + ``emit_outcome`` — terminal-record helper for node bodies (review §2.1).

Most graph nodes end the same way: ``observe(decision=..., output=...)`` to write the
ledger entry, and (when the node has observable side effects) ``emit_for(writer, state,
EVENT, payload)`` for downstream subscribers. Two sinks, kept in sync by hand at every
call site.

``NodeOutcome`` lets a node describe its terminal state in one object; ``emit_outcome``
fans that out to both sinks. ``log.X(...)`` calls stay as direct lines next to the
``emit_outcome`` call — printf-style positional args + variadic kwargs don't fit a
clean dataclass shape, and forcing them through one would obscure the log call rather
than clarify it.

Early ``observe(input=...)`` calls (made before the work that records them) also stay
as direct ``observe`` calls — buffering them to the end would lose context on a re-raise.

The unification target is the END-of-path pair ``(observe decision+output, emit_for event)``.
Both sinks' wire formats are unchanged: ``observe`` writes the same ledger row fields,
``emit_for`` merges the same identity keys. Ledger CSV and event payload format stay
byte-identical (this is what the fixture regression tests gate).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .graph_kit import IDENTITY_KEYS, emit_for
from .ledger import observe


@dataclass(frozen=True)
class NodeOutcome:
    """Terminal record for one node — fans out to ledger + event sinks.

    Fields are optional so a node only describes the sinks it touches. ``fail`` is
    mutually exclusive with ``decision``/``output``/``usage`` (matching ``observe``'s
    fail-row contract: a failed entry doesn't also carry a successful decision).
    """

    decision: tuple[str, str] | None = None
    output: str | None = None
    # Pass-through to ``observe(output_max_len=...)`` when the preview can legitimately
    # exceed the default 280-char cap (knowledge retrieval rows use ``KNOWLEDGE_PREVIEW_MAX``).
    output_max_len: int | None = None
    usage: dict[str, Any] | None = None
    # ``(event_name, payload)`` routed through ``emit_for`` so turn identity merges in.
    event: tuple[str, dict[str, Any]] | None = None
    # Override the identity-key tuple when the event is peer-scoped (e.g. ``reply.completed``
    # uses ``IDENTITY_PEER_KEYS``). Defaults to chat ``IDENTITY_KEYS`` when unset.
    event_identity_keys: tuple[str, ...] = IDENTITY_KEYS
    # Failure shape — short-circuits decision/output. Matches ``observe(fail=...)``.
    fail: dict[str, Any] | None = None


def emit_outcome(
    writer: Any,
    state: dict[str, Any],
    outcome: NodeOutcome,
) -> None:
    """Apply a ``NodeOutcome`` to both sinks in canonical order: ledger first, then event."""
    if outcome.fail is not None:
        observe(fail=outcome.fail)
    else:
        kwargs: dict[str, Any] = {}
        if outcome.decision is not None:
            kwargs["decision"] = outcome.decision
        if outcome.output is not None:
            kwargs["output"] = outcome.output
        if outcome.output_max_len is not None:
            kwargs["output_max_len"] = outcome.output_max_len
        if outcome.usage is not None:
            kwargs["usage"] = outcome.usage
        if kwargs:
            observe(**kwargs)
    if outcome.event is not None:
        name, payload = outcome.event
        emit_for(writer, state, name, payload, identity_keys=outcome.event_identity_keys)
