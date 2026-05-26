"""LangGraph implementation for admin knowledge retrieval and answering."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from hiro_commons.log import Logger
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter

from hirocli.domain.model_factory import create_chat_model
from hirocli.domain.preferences import resolve_knowledge_answering_llm
from hirocli.runtime.agent_graph.base import BaseAgentGraph
from hirocli.runtime.agent_graph.base import _llm_usage_payload as llm_usage_payload
from hirocli.runtime.agent_graph.base import _normalize_reply_content
from hirocli.runtime.agent_graph.events import GRAPH_LLM_USAGE
from hirocli.runtime.agent_graph.ledger import current_entry, graph_logged

from .helpers import (
    NormalizedQuery,
    build_context,
    build_qdrant_filter,
    matched_query_terms,
    normalize_query,
)

if TYPE_CHECKING:
    from hirocli.domain.preferences import WorkspacePreferences
    from hirocli.services.knowledge.models import KnowledgeSearchHit, KnowledgeSource

log = Logger.get("SVC.KNOWLEDGE.GRAPH")

KNOWLEDGE_NODE_PREFIX = "knowledge"


class KnowledgeAgentState(TypedDict, total=False):
    query: str
    filters: dict[str, Any]
    top_k: int
    min_score: float
    explain: bool
    normalized_query: NormalizedQuery
    qdrant_filter: Any
    query_vector: list[float]
    query_sparse_vector: Any
    hits: list[Any]
    sources: list[Any]
    context: str
    answer: str
    model_id: str | None
    usage: dict[str, Any]
    started_at: str
    elapsed_ms: int
    no_results: bool
    inbound_id: str
    chat_channel_id: int | str
    device_id: str
    user_id: str
    character_id: str


class KnowledgeAgentGraph(BaseAgentGraph):
    """Small LangGraph for knowledge search -> cited answer."""

    def __init__(
        self,
        *,
        workspace_path: Path,
        service: Any,
        prefs: "WorkspacePreferences",
        workspace_id: str | None = None,
    ) -> None:
        super().__init__(
            workspace_path=workspace_path,
            stt_service=None,
            vision_service=None,
            tts_service=None,
            credential_store=None,
            checkpointer=None,
            memory_service=None,
            preferences=None,
        )
        self._service = service
        self._prefs = prefs
        self._workspace_id = workspace_id

    def build(
        self,
        *,
        model: Any = None,
        tools: list | None = None,
        model_id: str = "",
        system_prompt: str | None = None,
    ) -> CompiledStateGraph:
        graph = StateGraph(KnowledgeAgentState)
        graph.add_node(
            "parse_query",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/parse_query", self.parse_query),
        )
        graph.add_node(
            "build_filters",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/build_filters", self.build_filters),
        )
        graph.add_node(
            "embed_query",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/embed_query", self.embed_query),
        )
        graph.add_node(
            "vector_search",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/vector_search", self.vector_search),
        )
        graph.add_node(
            "build_context",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/build_context", self.build_context),
        )
        graph.add_node(
            "call_model",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/call_model", self.call_model),
        )
        graph.add_node(
            "finalize",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/finalize", self.finalize),
        )
        graph.add_edge(START, "parse_query")
        graph.add_edge("parse_query", "build_filters")
        graph.add_edge("build_filters", "embed_query")
        graph.add_edge("embed_query", "vector_search")
        graph.add_edge("vector_search", "build_context")
        graph.add_conditional_edges(
            "build_context",
            self._route_after_context,
            {"call_model": "call_model", "finalize": "finalize"},
        )
        graph.add_edge("call_model", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    @staticmethod
    def _route_after_context(state: KnowledgeAgentState) -> str:
        if state.get("no_results"):
            return "finalize"
        return "call_model"

    def parse_query(self, state: KnowledgeAgentState) -> dict[str, Any]:
        normalized = normalize_query(state.get("query", ""))
        return {
            "normalized_query": normalized,
            "started_at": dt.datetime.now(dt.UTC).isoformat(),
        }

    def build_filters(self, state: KnowledgeAgentState) -> dict[str, Any]:
        return {"qdrant_filter": build_qdrant_filter(state.get("filters") or {})}

    @graph_logged()
    async def embed_query(self, state: KnowledgeAgentState) -> dict[str, Any]:
        normalized = state["normalized_query"]
        if entry := current_entry.get():
            entry.set_input_preview(f"text: {normalized.text[:200]}")
        vector = await self._service.embed_query(normalized.text)
        out: dict[str, Any] = {"query_vector": vector}
        # Only pay for the BM25 query embed when hybrid is enabled.
        if self._prefs.knowledge.retrieval.hybrid:
            out["query_sparse_vector"] = await self._service.embed_query_sparse(normalized.text)
        return out

    @graph_logged(captures={"decision"})
    async def vector_search(self, state: KnowledgeAgentState) -> dict[str, Any]:
        vector = state.get("query_vector") or []
        if not vector:
            if entry := current_entry.get():
                entry.set_decision("empty", "no_query_vector")
                entry.set_output_preview("hits: 0")
            return {"hits": []}
        retrieval = self._prefs.knowledge.retrieval
        hits = await self._service.vector_search_by_vector(
            vector,
            state.get("query_sparse_vector"),
            top_k=int(state.get("top_k") or retrieval.top_k),
            min_score=float(
                state["min_score"]
                if state.get("min_score") is not None
                else retrieval.min_score
            ),
            prefetch_limit=retrieval.prefetch_limit,
            hybrid=retrieval.hybrid,
            explain=bool(state.get("explain")),
            qdrant_filter=state.get("qdrant_filter"),
        )
        if entry := current_entry.get():
            entry.set_decision("ok", f"hits_{len(hits)}")
            entry.set_output_preview(f"hits: {len(hits)}")
        return {"hits": hits}

    def build_context(self, state: KnowledgeAgentState) -> dict[str, Any]:
        from hirocli.services.knowledge.converters import source_from_hit

        # matched_terms is a human-eval hint, computed only in opt-in explain mode.
        explain = bool(state.get("explain"))
        normalized = state.get("normalized_query")
        query_text = normalized.text if normalized is not None else str(state.get("query", ""))
        sources = []
        for index, hit in enumerate(state.get("hits") or [], start=1):
            terms = matched_query_terms(query_text, hit.text) if explain else None
            sources.append(source_from_hit(index, hit, matched_terms=terms))
        return {
            "sources": sources,
            "context": build_context(sources),
            "no_results": not bool(sources),
        }

    @graph_logged(captures={"usage", "decision"})
    async def call_model(
        self,
        state: KnowledgeAgentState,
        writer: StreamWriter | None = None,
    ) -> dict[str, Any]:
        resolved = resolve_knowledge_answering_llm(
            self._prefs,
            self._workspace_path,
            workspace_id=self._workspace_id,
        )
        normalized = state["normalized_query"]
        if entry := current_entry.get():
            entry.set_input_preview(f"text: {normalized.text[:200]}")
        if resolved is None:
            answer = self._fallback_answer(state)
            if entry := current_entry.get():
                entry.set_decision("skipped", "no_llm_configured")
                entry.set_output_preview(f"answer: {answer[:200]}")
            return {
                "answer": answer,
                "model_id": None,
                "usage": {},
            }
        model_id = resolved.model_id
        try:
            model = create_chat_model(
                model_id,
                workspace_path=self._workspace_path,
                workspace_id=self._workspace_id,
                temperature=resolved.temperature,
                max_tokens=resolved.max_tokens,
                thinking=resolved.thinking,
            )
        except Exception as exc:
            log.error("knowledge.answer model creation failed", error=str(exc), exc_info=True)
            answer = self._fallback_answer(state)
            if entry := current_entry.get():
                entry.set_decision("provider_error", "model_create_failed")
                entry.set_error("model_create_failed")
                entry.set_output_preview(f"answer: {answer[:200]}")
            return {"answer": answer, "model_id": model_id, "usage": {}}
        messages = [
            SystemMessage(content=self._system_prompt(normalized)),
            HumanMessage(content=f"Question:\n{normalized.text}\n\nContext:\n{state.get('context', '')}"),
        ]
        estimate = count_tokens_approximately(messages)
        try:
            response = await model.ainvoke(messages)
        except Exception as exc:
            log.error("knowledge.answer model call failed", error=str(exc), exc_info=True)
            answer = self._fallback_answer(state)
            if entry := current_entry.get():
                entry.set_decision("provider_error", "model_call_failed")
                entry.set_error("provider_error")
                entry.set_output_preview(f"answer: {answer[:200]}")
            return {"answer": answer, "model_id": model_id, "usage": {}}
        usage_payload = llm_usage_payload(
            response,
            inbound_id=str(state.get("inbound_id") or "knowledge.answer"),
            chat_channel_id=int(state.get("chat_channel_id") or 0),
            model_id=model_id,
            estimated_input_tokens=estimate,
        )
        answer = _normalize_reply_content(getattr(response, "content", ""))
        provider = model_id.split(":", 1)[0] if ":" in model_id else ""
        if entry := current_entry.get():
            entry.add_usage(
                provider=provider,
                model=model_id,
                input_tokens=int(usage_payload.get("input_tokens") or estimate or 0),
                output_tokens=int(usage_payload.get("output_tokens") or 0),
                cached_input_tokens=int(usage_payload.get("cached_input_tokens") or 0),
                reasoning_tokens=int(usage_payload.get("reasoning_tokens") or 0),
            )
            entry.set_decision("text_reply", "ok")
            entry.set_output_preview(
                f"answer: {answer[:200]}" if answer.strip() else "answer: <empty>"
            )
        if writer is not None:
            self._emit(writer, GRAPH_LLM_USAGE, usage_payload)
        return {
            "answer": answer,
            "model_id": model_id,
            "usage": usage_payload,
        }

    @graph_logged(captures={"decision"})
    def finalize(self, state: KnowledgeAgentState) -> dict[str, Any]:
        started_at = state.get("started_at")
        elapsed_ms = 0
        if started_at:
            try:
                started = dt.datetime.fromisoformat(started_at)
                elapsed_ms = int((dt.datetime.now(dt.UTC) - started).total_seconds() * 1000)
            except ValueError:
                elapsed_ms = 0
        if entry := current_entry.get():
            if state.get("no_results"):
                entry.set_decision("empty", "no_results")
                entry.set_output_preview("answer: <no_results>")
            else:
                answer = str(state.get("answer") or "")
                entry.set_decision("completed", "knowledge_answer")
                entry.set_output_preview(
                    f"answer: {answer[:200]}" if answer.strip() else "answer: <empty>"
                )
        return {"elapsed_ms": elapsed_ms}

    def _fallback_answer(self, state: KnowledgeAgentState) -> str:
        sources = state.get("sources") or []
        query = state.get("normalized_query")
        text = query.text if query is not None else state.get("query", "")
        lead = f"Found {len(sources)} relevant source(s) for: {text.strip()}"
        lines = [lead]
        for source in sources[:5]:
            snippet = " ".join(source.text.split())
            if len(snippet) > 280:
                snippet = snippet[:277].rstrip() + "..."
            citation = f" [{source.ref}]" if self._prefs.knowledge.answering.cite_sources else ""
            lines.append(f"- {snippet}{citation}")
        return "\n".join(lines)

    def _system_prompt(self, normalized: NormalizedQuery) -> str:
        parts = [
            "Answer using only the provided knowledge context.",
            "If the context is insufficient, say what is missing.",
        ]
        if self._prefs.knowledge.answering.cite_sources:
            parts.append("Cite evidence inline with footnote references like [1].")
        else:
            parts.append("Do not include footnote references or inline source markers.")
        policy = self._prefs.knowledge.answering.language_policy
        if policy == "prefer_english":
            parts.append("Answer in English.")
        elif policy == "prefer_arabic":
            parts.append("Answer in Arabic.")
        elif normalized.language == "ar":
            parts.append("Answer in the same language as the question, Arabic.")
        elif normalized.language and normalized.language != "unknown":
            parts.append(f"Answer in the same language as the question ({normalized.language}).")
        else:
            parts.append("Answer in the same language as the question when it is clear.")
        return " ".join(parts)
