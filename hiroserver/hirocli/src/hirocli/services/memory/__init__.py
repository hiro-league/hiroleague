"""Memory service factory."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hiro_commons.log import Logger

from hirocli.domain.memory import MemoryService

if TYPE_CHECKING:
    from hirocli.domain.credential_store import CredentialStore
    from hirocli.domain.preferences import WorkspacePreferences

log = Logger.get("SVC.MEMORY")


def create_memory_service(
    workspace_path: Path,
    prefs: "WorkspacePreferences",
    *,
    credential_store: "CredentialStore | None" = None,
) -> MemoryService | None:
    """Build the long-term conversation-memory service when enabled.

    Memory now rides the shared **Graphiti** graph brain (mem0 → Graphiti, Phase 3): a
    :class:`GraphitiConversationMemory` over a per-workspace :class:`GraphitiMemoryService`,
    isolated per ``(user, character)`` group. Gated by ``memory.enabled``; the engine is
    configured by the shared graph preferences (extraction model + embedder), NOT the
    knowledge-graph *retrieval* backend toggle — so memory builds even when graph retrieval
    is off (``require_backend=False``). Returns ``None`` (with a log) when memory is off or
    the engine can't be built (no extraction model / embedder configured).
    """
    memory_prefs = getattr(prefs, "memory", None)
    if not getattr(memory_prefs, "enabled", False):
        log.info("Memory service disabled by preferences")
        return None

    try:
        from hirocli.services.knowledge.graph.graphiti_service import GraphitiMemoryService

        graph_service = GraphitiMemoryService.from_preferences(
            prefs,
            workspace_path,
            credential_store=credential_store,
            require_backend=False,
            # No on_usage override: the client uses graphiti's default
            # ``record_episode_llm_usage`` sink, so the memory write's extraction tokens are
            # priced on the per-operation Graph-Runs sub-rows nested under ``memory_out``
            # (not lumped onto the parent row — avoids double-counting in the turn total).
        )
    except ImportError as exc:
        log.warning(
            "Memory service unavailable - graphiti-core / kuzu not installed",
            error=str(exc),
        )
        return None

    if graph_service is None:
        log.error(
            "Memory service disabled - Graphiti engine unavailable "
            "(configure the graph extraction model + embedder)",
        )
        return None

    from hirocli.services.knowledge.graph.graph_events import graph_event_bus_sink

    from .graphiti_conversation import GraphitiConversationMemory

    top_k = int(getattr(getattr(memory_prefs, "search", None), "top_k", 8))
    # Live viz: stream each remembered turn's new facts to the admin Graph tab (same
    # DomainEventBus the knowledge-graph ingest uses). Cheap when no Graph tab is watching.
    event_sink = graph_event_bus_sink(workspace_path)
    log.info("✅ memory — Graphiti conversation memory ready")
    return GraphitiConversationMemory(graph_service, default_top_k=top_k, event_sink=event_sink)
