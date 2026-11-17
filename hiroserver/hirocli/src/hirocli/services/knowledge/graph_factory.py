"""Build the memory engine's graph service from the core's workspace preferences.

The engine (``hiro_memory.graph``) reads no preferences and builds no models: this factory resolves
the model tiers from their AI profiles, the shared knowledge embedder and the graph reranker, and
hands them in, with the core's AI-usage counting.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hiro_commons.log import Logger
from hiro_memory.graph import GraphitiMemoryService, graphiti_db_path
from hiro_memory.graph.graphiti_adapters import (
    GraphitiEmbedderClient,
    GraphitiLLMClient,
    GraphitiLLMUsage,
    GraphitiModelSpec,
    HiroRerankerCrossEncoder,
    UsageSink,
)
from hiro_memory.graph.ingest_ledger import (
    current_ingest_episode,
    record_episode_embed,
    record_episode_llm_usage,
)
from hiro_memory.graph.ledger_tracer import record_rerank_usage

from hirocli.domain.model_factory import build_chat_model_from_tuning, with_structured_output_compat
from hirocli.domain.preferences import (
    ModelTuning,
    ResolvedModel,
    WorkspacePreferences,
    resolve_graph_reranker_model,
    resolve_graphiti_embedder_model,
    resolve_graphiti_extraction_model,
    resolve_graphiti_small_model,
)
from hirocli.services.ai_usage.from_ledger import count_graph_llm_usage

if TYPE_CHECKING:
    from graphiti_core.cross_encoder.client import CrossEncoderClient

    from hirocli.domain.credential_store import CredentialStore

log = Logger.get("SVC.KNOWLEDGE.GRAPH.GRAPHITI")

# Reranker ``top_n`` for the cross-encoder: rank ALL candidate facts Graphiti hands it
# (the final cut is Graphiti's ``SearchConfig.limit``). Generous so we never pre-trim.
_RERANK_CANDIDATE_CAP = 512


def _spec(resolved: ResolvedModel) -> GraphitiModelSpec:
    """ResolvedModel (id + profile params) → adapter spec."""
    return GraphitiModelSpec(
        model_id=resolved.model_id,
        tuning=ModelTuning(
            temperature=resolved.temperature,
            max_tokens=resolved.max_tokens,
            thinking=resolved.thinking,
            num_ctx=resolved.num_ctx,
        ),
    )


def _graph_usage_sink(workspace_path: Path, observe: bool) -> UsageSink:
    """The graph LLM client's usage hook (Phase 7b): inside an ingest episode with observability on, the
    episode's ledger row carries the call (and AI usage counts that row); otherwise AI usage counts the
    call itself, so the observability tier never hides what the graph costs."""
    return partial(_on_graph_usage, workspace_path, observe)


def _on_graph_usage(workspace_path: Path, observe: bool, usage: GraphitiLLMUsage) -> None:
    if observe and current_ingest_episode.get() is not None:
        record_episode_llm_usage(usage)
        return
    count_graph_llm_usage(workspace_path, usage)


def _model_builder(
    workspace_path: Path, workspace_id: str | None, credential_store: "CredentialStore | None"
) -> Any:
    def build(spec: GraphitiModelSpec) -> Any:
        return build_chat_model_from_tuning(
            spec.model_id,
            workspace_path=workspace_path,
            workspace_id=workspace_id,
            tuning=spec.tuning,
            credential_store=credential_store,
            callbacks=[],
        )

    return build


def _structured_output(model: Any, schema: Any) -> Any:
    # Provider quirks (DeepSeek thinking mode, Claude's forced tool choice) are the core's to handle.
    return with_structured_output_compat(model, schema, include_raw=True)


def build_graph_service(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: "CredentialStore | None" = None,
    on_usage: UsageSink | None = None,
    require_backend: bool = True,
) -> GraphitiMemoryService | None:
    """Build the graph service from workspace preferences, or ``None`` when unavailable.

    Returns ``None`` (no error) when ``knowledge.graph.backend`` is ``off``
    (unless ``require_backend=False`` — explicit build-graph/ingest actions still
    run with the backend toggle off) or no extraction model is configured. Same
    enable-gating shape as the prior mem0 service. Resolves both model tiers from
    their AI profiles (Phase 7b step 5) and the shared knowledge embedder (G8).
    """
    if require_backend and prefs.graph.backend == "off":
        log.info("⬇️ graphiti — backend=off · service not created")
        return None

    extraction = resolve_graphiti_extraction_model(
        prefs, workspace_path, workspace_id=workspace_id, credential_store=credential_store
    )
    if extraction is None:
        log.warning(
            "⚠️ graphiti — no extraction model available (pick an AI profile for "
            "graph.extraction_profile or llm.chat_profile) · service not created"
        )
        return None
    small = (
        resolve_graphiti_small_model(
            prefs, workspace_path, workspace_id=workspace_id, credential_store=credential_store
        )
        or extraction
    )

    # Shared embedder (G8): build the SAME knowledge backend (same model id ⇒
    # identical vectors). Lazy import keeps the heavy embedder deps off this
    # module's import path.
    from hirocli.services.knowledge.embedder import resolve_knowledge_embedder

    # No forced default: the graph needs a real embedder to build its vector index. Gate here
    # rather than silently picking a model (would orphan vectors on a later change).
    embedder_model_id = resolve_graphiti_embedder_model(prefs)
    if not embedder_model_id:
        raise ValueError(
            "No graph embedder configured. Set the Graph embedder, or a workspace default "
            "embedder (Preferences → General → Default models), before building the graph."
        )
    backend = resolve_knowledge_embedder(
        workspace_path, embedder_model_id, credential_store=credential_store
    )

    # Observability tier gates every usage sink: at ``off`` we wire NONE of them, so the
    # adapters skip the per-call hook entirely (the choke point that spares CPU). ``ledger``
    # and ``trace`` both capture usage — the difference is detail rendering, handled downstream.
    observability = prefs.graph.observability
    observe = observability != "off"

    llm_client = GraphitiLLMClient(
        medium=_spec(extraction),
        small=_spec(small),
        model_builder=_model_builder(workspace_path, workspace_id, credential_store),
        structured_output=_structured_output,
        # Route per-call usage into the active ingest episode (no-op outside
        # ingest, so retrieval/memory paths are unaffected). An explicit
        # ``on_usage`` still overrides for callers that want their own sink.
        # Phase 7b: AI usage counts every graph LLM call whatever the observability tier (it is
        # tracing detail, not counting); see _graph_usage_sink.
        on_usage=on_usage or _graph_usage_sink(workspace_path, observe),
    )
    embedder = GraphitiEmbedderClient(
        backend, on_embed=record_episode_embed if observe else None
    )

    # Cross-encoder reranker for the fact-search leg (only when the recipe asks for
    # it). Resolve the SAME reranker the flat path uses (cloud or local) and wrap it
    # as Graphiti's CrossEncoderClient. If it can't resolve (unconfigured / local
    # model not downloaded), degrade the recipe to RRF rather than ship a no-op that
    # masquerades as reranking.
    graph = prefs.graph
    recipe = graph.search_recipe
    cross_encoder: "CrossEncoderClient | None" = None
    reranker_min_score = 0.0
    if recipe == "cross_encoder":
        # Graph override, else the workspace default reranker (llm.default_reranker).
        reranker_model_id = resolve_graph_reranker_model(prefs)
        if reranker_model_id:
            try:
                from hirocli.services.knowledge.reranker import resolve_reranker

                compressor, _calibrated = resolve_reranker(
                    reranker_model_id,
                    workspace_path=workspace_path,
                    workspace_id=workspace_id,
                    top_n=_RERANK_CANDIDATE_CAP,  # rank ALL candidates; SearchConfig.limit cuts
                    device=graph.reranker.device,
                    credential_store=credential_store,
                )
                # Report rerank usage into the active recall accumulator so the ``rerank``
                # ledger node carries model + processed tokens and prices via the catalog
                # (no-op outside a ledgered search; cross_encoder never runs during ingest).
                cross_encoder = HiroRerankerCrossEncoder(
                    compressor,
                    model_id=reranker_model_id,
                    on_rank=record_rerank_usage if observe else None,
                )
                reranker_min_score = graph.reranker.min_relevance
                log.info("⬇️ graphiti — cross-encoder reranker · model=%s", reranker_model_id)
            except Exception:
                log.warning(
                    "⚠️ graphiti — cross-encoder reranker %r unavailable; falling back to "
                    "RRF (configure/download the reranker model)",
                    reranker_model_id,
                    exc_info=True,
                )
                recipe = "rrf"
        else:
            log.info(
                "⬇️ graphiti — search_recipe=cross_encoder but no reranker model set "
                "(graph.reranker.model_id / llm.default_reranker) · using RRF"
            )
            recipe = "rrf"

    return GraphitiMemoryService(
        db_path=graphiti_db_path(workspace_path),
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=cross_encoder,
        observability=observability,
        search_recipe=recipe,
        # Which graph elements participate in recall. Validated against ``search_recipe``
        # at pref load (mmr × episodes is rejected up-front), so any value reaching here
        # is a legal combo.
        search_scope=graph.search_scope,
        k_hop=graph.k_hop,
        reranker_min_score=reranker_min_score,
        sim_min_score=graph.sim_min_score,
        query_timeout_s=graph.query_timeout_s,
        entity_ontology=graph.entity_ontology,
        custom_extraction_instructions=graph.custom_extraction_instructions,
    )


def graph_query_timeout(workspace_path: Path) -> int:
    """The workspace's ``graph.query_timeout_s`` for the engine's snapshot reads; best effort.

    Every read takes the timeout from its caller (the engine reads no preferences). A preferences file
    that can't be read falls back to the setting's default, as the reads did before.
    """
    try:
        from hirocli.domain.preferences import load_preferences

        return int(load_preferences(workspace_path).graph.query_timeout_s)
    except Exception:
        log.warning("⚠️ graphiti — query-timeout pref read failed; using default", exc_info=True)
        return 60
