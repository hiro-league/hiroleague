"""PreferencesView — the single typed read path for the graph's preference needs.

Resolves the live snapshot once (runtime → disk fallback), logs+swallows a resolution failure
exactly once, and exposes typed getters whose defaults live here (not scattered across nodes).
"""

from __future__ import annotations

from hiro_commons.log import Logger

from ...domain.preferences import DEFAULT_MAX_HISTORY_MESSAGES

log = Logger.get("AGENT.GRAPH.PREFS")


class PreferencesView:
    def __init__(self, runtime, workspace_path) -> None:
        self._runtime = runtime
        self._workspace_path = workspace_path

    @property
    def current(self):
        """Live prefs snapshot, or a loaded copy, or None — the ONLY fallback site."""
        try:
            if self._runtime is not None:
                return self._runtime.current
            from ...domain.preferences import load_preferences

            return load_preferences(self._workspace_path)
        except Exception as exc:  # one place; nodes never wrap prefs reads again
            log.warning(
                "⚠️ prefs — resolve failed · using defaults",
                error=str(exc),
                exc_info=True,
            )
            return None

    def history_window(self) -> int:
        chat = getattr(self.current, "chat", None)
        return int(
            getattr(chat, "max_messages", DEFAULT_MAX_HISTORY_MESSAGES)
            or DEFAULT_MAX_HISTORY_MESSAGES
        )

    def cite_sources(self) -> bool:
        return bool(getattr(getattr(self.current, "chat", None), "cite_sources", False))

    def chat_instructions(self) -> str:
        return str(getattr(getattr(self.current, "chat", None), "instructions", "") or "")

    def memory(self):
        """The memory prefs sub-object (or None) — replaces getattr(...current..., 'memory')."""
        return getattr(self.current, "memory", None)

    def memory_recall_render(self):
        """Build the chat ``RecallRenderOptions`` from ``memory.retrieval.render`` (P3) — the temporal
        toggles + per-kind caps the memory block renders with. Defaults when prefs are unavailable."""
        from ...services.memory.agent.presentation import RecallRenderOptions

        retrieval = getattr(getattr(self.current, "memory", None), "retrieval", None)
        r = getattr(retrieval, "render", None)
        if r is None:
            return RecallRenderOptions()
        return RecallRenderOptions(
            show_event_time=bool(r.show_event_time),
            show_expired_at=bool(r.show_expired_at),
            show_superseded=bool(r.show_superseded),
            max_elements_per_kind=int(r.max_elements_per_kind),
            max_fact_chars=int(r.max_fact_chars),
            max_episode_chars=int(r.max_episode_chars),
            max_summary_chars=int(r.max_summary_chars),
        )
