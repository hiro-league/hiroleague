"""L3 eval — per-workspace, in-memory run registry (the live + replay store).

The admin Eval Batch panel needs three things the bare SSE stream can't give it:

* **Mid-run replay** — navigate away during a run and come back: the SSE
  connection closed, so every event that fired while disconnected is gone.
* **Cross-origin consistency** — the Vite dev UI (``localhost:5173``) and the
  packaged admin UI (the server's own port) are different browser origins with
  separate ``sessionStorage``. A purely client-side snapshot diverges between
  them; both must read the *same* server-side truth.
* **Cancellation** — a fire-and-forget eval task needs a handle the cancel
  endpoint can reach.

This module is that single source of truth. One process-wide registry subscribes
to the ``knowledge.eval.*`` Domain Events (the same ones the SSE stream relays)
and accumulates per-workspace state: the setup activity trail, the per-question
rows (with FULL answers, not just the SSE preview), and the final summary. The
``GET /knowledge/eval/state`` route reads it for replay; ``POST
/knowledge/eval/cancel`` reaches the stored task handle through it.

State lives only in the running server process — a restart drops it. That's the
right scope for a dev/eval tool: consistent across origins and across navigation
within a server lifetime, with no schema to migrate.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from hirocli.domain.events import DomainEvent, get_domain_event_bus
from hirocli.services.knowledge.constants import (
    KNOWLEDGE_EVAL_CANCELLED,
    KNOWLEDGE_EVAL_COMPLETED,
    KNOWLEDGE_EVAL_FAILED,
    KNOWLEDGE_EVAL_QUESTION_COMPLETED,
    KNOWLEDGE_EVAL_SETUP_PROGRESS,
    KNOWLEDGE_EVAL_STARTED,
)

log = Logger.get("SVC.KNOWLEDGE.EVAL.REGISTRY")

# Safety cap on the setup activity trail (per-episode lines can pile up on a big
# corpus). The terminal is a tail view anyway; oldest lines drop first.
_MAX_SETUP_EVENTS = 4000


@dataclass
class EvalRunState:
    """Accumulated state of one eval run, keyed per workspace.

    Mirrors what the panel renders: the setup activity trail (``setup_events``),
    the per-question ``rows`` (each the full ``question_completed`` payload,
    answers included), and the terminal ``summary``. ``task`` is the live
    asyncio handle — non-serialized; cancel reaches it, ``to_payload`` skips it.
    """

    run_id: str
    corpus_source: str = ""
    status: str = "starting"  # starting | running | completed | failed | cancelled
    total_questions: int = 0
    # Selected legs for this run (subset of flat/graphiti/mix) — drives the UI's
    # dynamic columns. Set at begin_run and confirmed by the ``started`` event.
    modes: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    setup_events: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] | None = None
    failure_message: str | None = None
    cancel_requested: bool = False
    task: asyncio.Task[Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        """JSON-serializable snapshot for ``GET /knowledge/eval/state``.

        Deliberately omits ``task`` (not serializable, and the client only needs
        to know *whether* a run is cancellable, which ``status`` already tells it)."""
        return {
            "run_id": self.run_id,
            "corpus_source": self.corpus_source,
            "status": self.status,
            "total_questions": self.total_questions,
            "modes": self.modes,
            "filters": self.filters,
            "setup_events": self.setup_events,
            "rows": self.rows,
            "summary": self.summary,
            "failure_message": self.failure_message,
            "cancel_requested": self.cancel_requested,
        }


_TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class EvalRunRegistry:
    """Process-wide store of the latest eval run per workspace.

    Subscribes once to the ``knowledge.eval.*`` Domain Events and folds them into
    per-workspace :class:`EvalRunState`. Only the *latest* run per workspace is
    kept — a new run replaces the slot (the panel shows one run at a time)."""

    def __init__(self) -> None:
        self._runs: dict[str, EvalRunState] = {}
        self._subscribed = False

    # -- keying -----------------------------------------------------------

    @staticmethod
    def _key(workspace_path: Path) -> str:
        try:
            return str(Path(workspace_path).resolve())
        except OSError:
            return str(Path(workspace_path))

    # -- subscription -----------------------------------------------------

    def ensure_subscribed(self) -> None:
        """Subscribe the (stable) handler to every eval event type, once.

        Idempotent — the bus dedupes by handler identity, and we guard with a
        flag so repeated route calls don't re-walk the type list. Called from the
        eval-run route before the background task starts, so the handler is live
        before any event fires."""
        if self._subscribed:
            return
        bus = get_domain_event_bus()
        for event_type in (
            KNOWLEDGE_EVAL_STARTED,
            KNOWLEDGE_EVAL_SETUP_PROGRESS,
            KNOWLEDGE_EVAL_QUESTION_COMPLETED,
            KNOWLEDGE_EVAL_COMPLETED,
            KNOWLEDGE_EVAL_FAILED,
            KNOWLEDGE_EVAL_CANCELLED,
        ):
            bus.subscribe(event_type, self._on_event)
        self._subscribed = True

    # -- run lifecycle (direct, from the route) ---------------------------

    def begin_run(
        self,
        workspace_path: Path,
        run_id: str,
        *,
        corpus_source: str,
        modes: list[str],
        task: asyncio.Task[Any],
    ) -> EvalRunState:
        """Open a fresh run slot and stash its task handle (for cancel).

        Called synchronously from the route the moment the background task is
        spawned, so a cancel that arrives before the first ``started`` event still
        finds a handle. The async ``started`` handler later fills in totals."""
        state = EvalRunState(
            run_id=run_id, corpus_source=corpus_source, modes=list(modes), task=task
        )
        self._runs[self._key(workspace_path)] = state
        return state

    def get_run(self, workspace_path: Path) -> EvalRunState | None:
        return self._runs.get(self._key(workspace_path))

    def request_cancel(self, workspace_path: Path, run_id: str | None = None) -> bool:
        """Cancel the live run for ``workspace_path`` (optionally run_id-gated).

        Returns True if a cancellable task was found and ``.cancel()`` was issued.
        The actual ``cancelled`` terminal event comes from the runner catching
        ``CancelledError`` — we only flip the intent flag and poke the task."""
        state = self._runs.get(self._key(workspace_path))
        if state is None:
            return False
        if run_id is not None and state.run_id != run_id:
            return False
        if state.status in _TERMINAL_STATUSES:
            return False
        state.cancel_requested = True
        task = state.task
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    # -- event folding (async, from the bus) ------------------------------

    async def _on_event(self, event: DomainEvent) -> None:
        """Fold one eval Domain Event into the matching workspace's run state.

        Run-correlation is by ``run_id`` when the slot already exists; a slot is
        always present in practice because the route's ``begin_run`` precedes the
        first event. Unknown/foreign runs are ignored."""
        state = self._runs.get(self._key(event.workspace_path))
        if state is None:
            return
        payload = event.payload or {}
        run_id = payload.get("run_id")
        # started/completed/failed/cancelled always carry run_id; setup/question
        # carry it too now (added in eval_runner). Drop stragglers from a prior run.
        if run_id is not None and run_id != state.run_id:
            return

        etype = event.type
        if etype == KNOWLEDGE_EVAL_STARTED:
            state.status = "running"
            state.total_questions = int(payload.get("total_questions") or 0)
            state.filters = dict(payload.get("filters") or {})
            # Confirm the leg set from the runner (authoritative over begin_run).
            if payload.get("modes"):
                state.modes = list(payload["modes"])
        elif etype == KNOWLEDGE_EVAL_SETUP_PROGRESS:
            state.setup_events.append(dict(payload))
            if len(state.setup_events) > _MAX_SETUP_EVENTS:
                # Tail view — drop the oldest, keep the recent trail bounded.
                del state.setup_events[: len(state.setup_events) - _MAX_SETUP_EVENTS]
        elif etype == KNOWLEDGE_EVAL_QUESTION_COMPLETED:
            self._upsert_row(state, dict(payload))
        elif etype == KNOWLEDGE_EVAL_COMPLETED:
            state.summary = dict(payload)
            state.status = "completed"
        elif etype == KNOWLEDGE_EVAL_FAILED:
            state.failure_message = str(payload.get("error") or "Eval run failed.")
            state.status = "failed"
        elif etype == KNOWLEDGE_EVAL_CANCELLED:
            state.status = "cancelled"

    @staticmethod
    def _upsert_row(state: EvalRunState, payload: dict[str, Any]) -> None:
        """Append (or replace, on duplicate delivery) a question row by index."""
        index = payload.get("index")
        for i, existing in enumerate(state.rows):
            if existing.get("index") == index:
                state.rows[i] = payload
                return
        state.rows.append(payload)


_REGISTRY = EvalRunRegistry()


def get_eval_registry() -> EvalRunRegistry:
    """Return the process-wide eval run registry."""
    return _REGISTRY
