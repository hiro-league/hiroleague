"""PreferenceReactor — in-process reactions to ``preferences.saved`` domain events.

Subsystems (STT, TTS, AgentManager, …) self-register reactions for one or more
preference dot-path prefixes. When ``preferences.json`` is saved with real value
transitions, matching reactions run on the runtime event loop, debounced per
reaction key so a burst of edits collapses into one rebuild.

Path matching
-------------
A reaction for prefix ``P`` triggers when an effective change at path ``C``
either:

  * equals ``P`` (exact leaf match — e.g. ``llm.default_stt``), or
  * is below ``P`` (``C`` starts with ``P + "."`` — e.g. ``llm.tuning`` covers
    ``llm.tuning.openai:gpt-5.temperature``), or
  * is above ``P`` (``P`` starts with ``C + "."`` — e.g. a reaction on
    ``llm.tuning.openai:stt`` still fires when the whole ``llm.tuning`` dict
    is replaced).

Threading
---------
Subscribed via :class:`hirocli.domain.events.DomainEventBus`, which guarantees
handlers run on the loop attached at server startup. Reactions therefore
execute as plain coroutines on that loop; long-blocking work should yield via
``asyncio.to_thread`` inside the reaction itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from ..domain.events import (
    DomainEvent,
    DomainEventBus,
    DomainEventType,
    get_domain_event_bus,
)

log = Logger.get("PREFERENCES.REACTOR")


# Reaction handler: receives the workspace path plus the subset of effective
# changes that matched the registered prefix.
ReactionHandler = Callable[
    [Path, dict[str, tuple[Any, Any]]],
    Awaitable[None],
]


@dataclass
class _Reaction:
    prefix: str
    handler: ReactionHandler
    key: str
    debounce_ms: int
    pending_changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    debounce_task: asyncio.Task[None] | None = None


class PreferenceReactor:
    """Per-workspace dispatcher for preference change reactions.

    One instance lives on :class:`ServerContext`. Subsystems call :meth:`on_change`
    during their startup (e.g. ``AgentManager.serve``) and :meth:`close` is
    invoked from the server shutdown path.
    """

    def __init__(
        self,
        workspace_path: Path,
        *,
        bus: DomainEventBus | None = None,
    ) -> None:
        self._workspace_path = workspace_path
        self._bus = bus or get_domain_event_bus()
        self._reactions: list[_Reaction] = []
        self._subscribed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_change(
        self,
        prefix: str,
        handler: ReactionHandler,
        *,
        key: str,
        debounce_ms: int = 150,
    ) -> None:
        """Register a reaction for ``prefix``.

        ``key`` identifies the reaction for debounce coalescing and logs;
        registering a second reaction with the same ``key`` replaces the prior
        one to keep ownership unambiguous (subsystems re-register on rebuild).
        """
        prefix = prefix.strip()
        if not prefix:
            raise ValueError("PreferenceReactor.on_change requires a non-empty prefix")
        if not key:
            raise ValueError("PreferenceReactor.on_change requires a non-empty key")
        if debounce_ms < 0:
            raise ValueError("debounce_ms must be >= 0")

        existing = next((r for r in self._reactions if r.key == key), None)
        if existing is not None:
            self._cancel_pending(existing)
            self._reactions.remove(existing)

        self._reactions.append(
            _Reaction(prefix=prefix, handler=handler, key=key, debounce_ms=debounce_ms)
        )
        self._ensure_subscribed()
        log.fineinfo(
            "Reaction registered — preferences",
            key=key,
            prefix=prefix,
            debounce_ms=debounce_ms,
        )

    def close(self) -> None:
        """Unsubscribe from the bus and cancel pending debounce tasks."""
        if self._subscribed:
            self._bus.unsubscribe(
                DomainEventType.PREFERENCES_SAVED, self._on_preferences_saved,
            )
            self._subscribed = False
        for reaction in self._reactions:
            self._cancel_pending(reaction)
        self._reactions.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_subscribed(self) -> None:
        if self._subscribed:
            return
        self._bus.subscribe(
            DomainEventType.PREFERENCES_SAVED, self._on_preferences_saved,
        )
        self._subscribed = True

    async def _on_preferences_saved(self, event: DomainEvent) -> None:
        if event.workspace_path != self._workspace_path:
            return
        changes = event.payload.get("effective_changes") or {}
        if not changes:
            return

        for reaction in list(self._reactions):
            matched = _select_changes_for_prefix(changes, reaction.prefix)
            if not matched:
                continue
            reaction.pending_changes.update(matched)
            self._schedule(reaction)

    def _schedule(self, reaction: _Reaction) -> None:
        if reaction.debounce_task is not None and not reaction.debounce_task.done():
            return  # Burst already scheduled; pending_changes accumulates until it fires.
        loop = asyncio.get_running_loop()
        reaction.debounce_task = loop.create_task(
            self._run_after_debounce(reaction),
            name=f"pref-reaction-{reaction.key}",
        )

    async def _run_after_debounce(self, reaction: _Reaction) -> None:
        try:
            if reaction.debounce_ms > 0:
                await asyncio.sleep(reaction.debounce_ms / 1000.0)
            changes = reaction.pending_changes
            reaction.pending_changes = {}
            if not changes:
                return
            t0 = asyncio.get_running_loop().time()
            try:
                await reaction.handler(self._workspace_path, changes)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error(
                    f"❌ reaction failed — {reaction.key}",
                    error=str(exc),
                    paths=sorted(changes.keys()),
                    exc_info=True,
                )
                return
            elapsed_ms = int((asyncio.get_running_loop().time() - t0) * 1000)
            log.info(
                f"✅ reaction applied — {reaction.key}",
                paths=sorted(changes.keys()),
                elapsed_ms=elapsed_ms,
            )
        finally:
            reaction.debounce_task = None

    @staticmethod
    def _cancel_pending(reaction: _Reaction) -> None:
        task = reaction.debounce_task
        if task is not None and not task.done():
            task.cancel()
        reaction.debounce_task = None
        reaction.pending_changes = {}


def _select_changes_for_prefix(
    changes: dict[str, tuple[Any, Any]],
    prefix: str,
) -> dict[str, tuple[Any, Any]]:
    """Return the subset of ``changes`` whose paths match ``prefix``.

    See module docstring for the three match cases (exact / below / above).
    """
    matched: dict[str, tuple[Any, Any]] = {}
    prefix_dot = prefix + "."
    for path, transition in changes.items():
        if path == prefix:
            matched[path] = transition
        elif path.startswith(prefix_dot):
            matched[path] = transition
        elif prefix.startswith(path + "."):
            matched[path] = transition
    return matched
