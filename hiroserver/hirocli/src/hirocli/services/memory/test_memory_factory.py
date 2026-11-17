"""The core's conversation-memory factory (Phase 3: mem0 → Graphiti re-point)."""

from __future__ import annotations

from hiro_memory.conversation.graphiti_conversation import GraphitiConversationMemory


class _FakeGraph:
    """Stands in for the graph service; the factory only wraps it."""

    async def close(self) -> None:
        pass


def test_create_memory_service_none_when_memory_disabled(tmp_path) -> None:
    from hirocli.domain.preferences import MemoryPreferences, WorkspacePreferences
    from hirocli.services.memory import create_memory_service

    prefs = WorkspacePreferences(memory=MemoryPreferences(enabled=False))
    assert create_memory_service(tmp_path, prefs) is None


def test_create_memory_service_none_when_engine_unavailable(tmp_path) -> None:
    """Memory enabled but no graph engine configured (no extraction model / embedder) →
    None, gracefully (``build_graph_service`` returns None, never raises)."""
    from hirocli.domain.preferences import MemoryPreferences, WorkspacePreferences
    from hirocli.services.memory import create_memory_service

    prefs = WorkspacePreferences(memory=MemoryPreferences(enabled=True))
    assert create_memory_service(tmp_path, prefs) is None


def test_create_memory_service_builds_graphiti_conversation(tmp_path, monkeypatch) -> None:
    """When enabled and the engine builds, the factory wraps the GraphitiMemoryService in a
    GraphitiConversationMemory, building even when graph RETRIEVAL is off
    (``require_backend=False``)."""
    from hirocli.domain.preferences import MemoryPreferences, WorkspacePreferences
    from hirocli.services.knowledge import graph_factory
    from hirocli.services.memory import create_memory_service

    captured: dict = {}

    def _fake_from_prefs(prefs, workspace_path, **kwargs):
        captured["require_backend"] = kwargs.get("require_backend")
        captured["on_usage"] = kwargs.get("on_usage", "unset")
        return _FakeGraph()

    monkeypatch.setattr(graph_factory, "build_graph_service", _fake_from_prefs)

    prefs = WorkspacePreferences(memory=MemoryPreferences(enabled=True))
    service = create_memory_service(tmp_path, prefs)

    assert isinstance(service, GraphitiConversationMemory)
    assert captured["require_backend"] is False  # builds even when graph retrieval is off
    # No on_usage override passed: the client falls back to graphiti's default
    # ``record_episode_llm_usage`` sink, which prices the write on the nested Graph-Runs
    # sub-rows (not a separate MemoryUsage on the parent memory_out row).
    assert captured["on_usage"] == "unset"

