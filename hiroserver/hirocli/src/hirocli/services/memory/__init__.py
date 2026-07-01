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
    # Snapshot the temporal lens at construction (replaces the former D8 hardcoded "current"):
    # memory recall now follows ``graph.temporal_default`` like every other leg. The
    # agent_manager reactor rebuilds this service on any ``graph.*`` change, so flipping
    # Settings → Graph → Temporal lens (default) re-snapshots automatically.
    temporal_default = prefs.graph.temporal_default
    # Live viz: stream each remembered turn's new facts to the admin Graph tab (same
    # DomainEventBus the knowledge-graph ingest uses). Cheap when no Graph tab is watching.
    event_sink = graph_event_bus_sink(workspace_path)
    log.info(
        "✅ memory — Graphiti conversation memory ready · temporal=%s",
        temporal_default,
    )
    return GraphitiConversationMemory(
        graph_service,
        default_top_k=top_k,
        temporal_default=temporal_default,
        event_sink=event_sink,
        # Chat ingests windowed two-speaker episodes → append the memory extraction clause
        # (memory.extraction.instructions; default = attribute facts to the user only, agent lines as
        # context). Eval leaves this blank (its corpus stays two-sided, extracting every speaker).
        extraction_instructions=str(
            getattr(getattr(memory_prefs, "extraction", None), "instructions", "") or ""
        ),
    )


def create_eval_memory_service(
    workspace_path: Path,
    prefs: "WorkspacePreferences",
    *,
    set_id: str,
    credential_store: "CredentialStore | None" = None,
) -> MemoryService:
    """Build an **eval-scoped** conversation-memory service bound to ``eval_mem_{set}``.

    The memory-eval track (docs/eval-corpus-tracks-design.md §6/§8) exercises the *real*
    ``remember``/``recall`` engine, but lands its data in a dedicated ``eval_mem_{set}`` drawer
    via the scoped-service-object override — so it never touches a real ``mem_{user}_{character}``
    group. Unlike :func:`create_memory_service` this is **independent of ``memory.enabled``** (eval
    must run even when the runtime memory toggle is off) and **fails loud** (raises) when the
    Graphiti engine can't be built, rather than returning ``None`` — a silent eval is worse than a
    clear error.
    """
    from hirocli.services.knowledge.graph.graphiti_service import GraphitiMemoryService
    from hirocli.services.knowledge.graph.group_scope import eval_memory_group_id

    from .graphiti_conversation import GraphitiConversationMemory

    # require_backend=False: the eval builds even when knowledge-graph *retrieval* is toggled off
    # (it only needs the extraction model + embedder), mirroring create_memory_service.
    graph_service = GraphitiMemoryService.from_preferences(
        prefs, workspace_path, credential_store=credential_store, require_backend=False
    )
    if graph_service is None:
        raise RuntimeError(
            "Memory eval: the Graphiti engine is unavailable — configure the graph extraction "
            "model + embedder (graph.extraction_model or knowledge.answering.model + provider key)."
        )

    from hirocli.services.knowledge.graph.graph_events import graph_event_bus_sink

    group = eval_memory_group_id(set_id)
    top_k = int(getattr(getattr(getattr(prefs, "memory", None), "search", None), "top_k", 8))
    # Eval mirrors the runtime: read the admin temporal lens from prefs (replaces D8 hardcode)
    # so the Memory eval reproduces what the agent will actually see at recall time.
    temporal_default = prefs.graph.temporal_default
    log.info(
        "✅ memory — eval-scoped conversation memory ready · group=%s · temporal=%s",
        group,
        temporal_default,
    )
    return GraphitiConversationMemory(
        graph_service,
        default_top_k=top_k,
        temporal_default=temporal_default,
        event_sink=graph_event_bus_sink(workspace_path),
        group_override=group,
    )
