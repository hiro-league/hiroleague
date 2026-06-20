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
