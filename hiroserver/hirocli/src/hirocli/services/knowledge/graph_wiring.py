"""The core's side of the knowledge engine: builds the ``KnowledgeGraphConfig`` the memory library's graph runs on.

The engine (``hiro_memory.knowledge.agent``) never reads the core's preferences, catalog or credentials. This module
hands it the settings values from a preferences snapshot, and the models, reranker and graph leg resolved the core's
way, behind callables that run when each step runs (as the steps resolved them before they moved to the library).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hiro_memory.knowledge.agent import (
    KnowledgeGraphConfig,
    KnowledgeGraphLeg,
    KnowledgeModel,
    KnowledgeReranker,
)
from hiro_memory.knowledge.graph_session import GraphitiSession, open_graphiti_session
from hiro_memory.knowledge.settings import KnowledgeSettings

from hirocli.domain.model_catalog import get_model_catalog
from hirocli.domain.model_factory import create_chat_model, with_structured_output_compat
from hirocli.domain.preferences import (
    ResolvedModel,
    resolve_knowledge_answering_llm,
    resolve_knowledge_embedder_model,
    resolve_knowledge_reranker_profile,
    resolve_knowledge_rewrite_llm,
)
from hirocli.runtime.agent_graph.events import GRAPH_LLM_USAGE
from hirocli.runtime.agent_graph.graph_kit import emit

if TYPE_CHECKING:
    from hirocli.domain.preferences import WorkspacePreferences


def knowledge_settings(prefs: "WorkspacePreferences") -> KnowledgeSettings:
    """The engine's settings values from the workspace preferences (the profile picks stay here)."""
    knowledge = prefs.knowledge
    return KnowledgeSettings.model_validate(
        {
            "retrieval": knowledge.retrieval.model_dump(),
            "answering": knowledge.answering.model_dump(),
            "rewrite": knowledge.rewrite.model_dump(),
            "graph_temporal_default": prefs.graph.temporal_default,
        }
    )


def _knowledge_model(
    resolved: ResolvedModel,
    workspace_path: Path,
    workspace_id: str | None,
    *,
    structured_output: bool = True,
) -> KnowledgeModel:
    def build():
        return create_chat_model(
            resolved.model_id,
            workspace_path=workspace_path,
            workspace_id=workspace_id,
            temperature=resolved.temperature,
            max_tokens=resolved.max_tokens,
            thinking=resolved.thinking,
            num_ctx=resolved.num_ctx,
        )

    return KnowledgeModel(
        model_id=resolved.model_id,
        build=build,
        temperature=resolved.temperature,
        max_tokens=resolved.max_tokens,
        thinking=resolved.thinking,
        structured_output=structured_output,
    )


def _supports_structured_output(model_id: str) -> bool:
    spec = get_model_catalog().get_model(model_id)
    return spec is not None and "structured_output" in spec.features


def graphiti_session(
    prefs: "WorkspacePreferences",
    workspace_path: Path,
    workspace_id: str | None = None,
) -> AbstractAsyncContextManager[GraphitiSession | None]:
    """Open the graph leg's Graphiti session, built from the workspace's graph preferences."""
    from hirocli.services.knowledge.graph_factory import build_graph_service

    return open_graphiti_session(
        build_graph_service(prefs, workspace_path, workspace_id=workspace_id),
        trace=prefs.graph.observability == "trace",
    )


def _structured_output(model: Any, schema: Any) -> Any:
    # The compat wrapper keeps DeepSeek thinking mode from 400ing on a forced tool_choice (json_mode fallback).
    return with_structured_output_compat(model, schema, include_raw=True)


def _emit_usage(writer: Any, payload: dict[str, Any]) -> None:
    emit(writer, GRAPH_LLM_USAGE, payload)


def knowledge_graph_config(
    service: Any,
    prefs: "WorkspacePreferences",
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
) -> KnowledgeGraphConfig:
    """The engine's config for one build: ``service`` retrieves (``KnowledgeService`` or a test fake), ``prefs`` is
    this build's snapshot."""
    workspace_path = Path(workspace_path)

    def answering_model() -> KnowledgeModel | None:
        resolved = resolve_knowledge_answering_llm(prefs, workspace_path, workspace_id=workspace_id)
        return _knowledge_model(resolved, workspace_path, workspace_id) if resolved is not None else None

    def rewrite_model() -> KnowledgeModel | None:
        resolved = resolve_knowledge_rewrite_llm(prefs, workspace_path, workspace_id=workspace_id)
        if resolved is None:
            return None
        return _knowledge_model(
            resolved,
            workspace_path,
            workspace_id,
            structured_output=_supports_structured_output(resolved.model_id),
        )

    def reranker() -> KnowledgeReranker | None:
        # The knowledge's reranker profile (knowledge.retrieval.reranker.profile): its model and device.
        profile = resolve_knowledge_reranker_profile(prefs)
        if profile is None or not profile.model:
            return None

        async def rerank(query: str, hits: list, top_n: int) -> list:
            return await service.rerank_hits(
                query,
                hits,
                model_id=profile.model,
                top_n=top_n,
                device=profile.device,
                workspace_id=workspace_id,
            )

        return KnowledgeReranker(model_id=profile.model, rerank=rerank)

    def query_timeout_s() -> int:
        from hirocli.services.knowledge.graph_factory import graph_query_timeout

        return graph_query_timeout(workspace_path)

    return KnowledgeGraphConfig(
        engine=service,
        settings=knowledge_settings(prefs),
        answering_model=answering_model,
        rewrite_model=rewrite_model,
        reranker=reranker,
        # Effective knowledge embedder (the embedding profile's model); None when unconfigured.
        embedder_model=resolve_knowledge_embedder_model(prefs),
        graph=KnowledgeGraphLeg(
            workspace_path=workspace_path,
            open_session=lambda: graphiti_session(prefs, workspace_path, workspace_id),
            query_timeout_s=query_timeout_s,
        ),
        emit_usage=_emit_usage,
        structured_output=_structured_output,
    )
