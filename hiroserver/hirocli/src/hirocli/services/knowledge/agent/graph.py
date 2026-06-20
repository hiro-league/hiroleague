"""LangGraph implementation for admin knowledge retrieval and answering."""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from hiro_commons.log import Logger
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter

from hirocli.domain.model_catalog import get_model_catalog
from hirocli.domain.model_factory import create_chat_model, with_structured_output_compat
from hirocli.domain.preferences import (
    DEFAULT_KNOWLEDGE_ANSWERING_PROMPT,
    DEFAULT_KNOWLEDGE_REWRITE_PROMPT,
    resolve_knowledge_answering_llm,
    resolve_knowledge_rewrite_llm,
)
from hirocli.runtime.agent_graph.events import GRAPH_LLM_USAGE
from hirocli.runtime.agent_graph.graph_kit import (
    KNOWLEDGE_PREVIEW_MAX,
    emit,
    estimate_text_tokens,
    knowledge_results_rows,
    llm_usage_payload,
    normalize_reply_content,
)
from hirocli.runtime.agent_graph.ledger import (
    current_entry,
    graph_logged,
    observe,
)
from hirocli.runtime.agent_graph.node_group import NodeGroup
from hirocli.runtime.agent_graph.services import AgentServices
from hirocli.services.knowledge.graph.graphiti_session import graphiti_session

# Runtime import (NOT TYPE_CHECKING): ``KnowledgeAgentState`` is a LangGraph ``StateGraph``
# schema; LangGraph evaluates its annotations via ``get_type_hints`` at build time, so these
# names must resolve at runtime despite ``from __future__ import annotations``.
from hirocli.services.knowledge.models import KnowledgeSearchHit, KnowledgeSource

from .helpers import (
    NormalizedQuery,
    QueryRewrite,
    build_context,
    build_qdrant_filter,
    matched_query_terms,
    normalize_query,
)
from .legs import RetrievalLeg, effective_leg, graphiti_facts_block, intended_leg

if TYPE_CHECKING:
    from hirocli.domain.preferences import WorkspacePreferences

log = Logger.get("SVC.KNOWLEDGE.GRAPH")

KNOWLEDGE_NODE_PREFIX = "knowledge"


def _is_valid_vector(vector: Any) -> bool:
    """A usable dense query vector is non-empty and finite; an empty/NaN vector means the embedder
    returned garbage and retrieval should not proceed on it."""
    try:
        if not len(vector):
            return False
        return math.isfinite(float(vector[0]))
    except (TypeError, ValueError, IndexError):
        return False


def _minmax_relevances(scores: list[float]) -> list[float]:
    """Min-max normalize retrieval scores into [0, 1] *within this result set* (ordinal).

    Used for the score contract when no reranker ran — RRF/cosine scores are not calibrated, so
    the top hit maps to 1.0 and the lowest to 0.0. A degenerate (all-equal) set maps all to 1.0.
    """
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi <= lo:
        return [1.0 for _ in scores]
    span = hi - lo
    return [(score - lo) / span for score in scores]


class KnowledgeAgentState(TypedDict, total=False):
    """Per-invoke scratch for the knowledge retrieval / answering graph.

    Compiled without a checkpointer (``build_retrieval()``) or with ephemeral runs only —
    no cross-call persistence. Every field is written during a single invocation and may be
    absent at entry.
    """

    # --- Query in ---
    query: str
    filters: dict[str, Any]
    top_k: int
    min_score: float
    explain: bool
    rewrite: bool
    graph_mode: str
    graph_temporal: str
    history: str

    # --- Rewrite output ---
    rewrite_keywords: list[str]
    knowledge_needed: bool
    rewritten_query: str | None
    normalized_query: NormalizedQuery
    query_entities: list[str]

    # --- Graph leg (graphiti) ---
    graph_facts: list[str]
    graph_chunk_ids: list[str]
    # Set by graph_expand: the resolved leg after the soft-fallback. Downstream nodes read THIS,
    # not graph_mode + chunk_ids. Values: RetrievalLeg.value ("flat" | "graphiti").
    effective_leg: str

    # --- Vector leg ---
    qdrant_filter: Any
    query_vector: list[float]
    query_sparse_vector: Any
    hits: list[KnowledgeSearchHit]
    reranked: bool

    # --- Assembly / answer ---
    sources: list[KnowledgeSource]
    context: str
    answer: str
    model_id: str | None
    usage: dict[str, Any]
    no_results: bool

    # --- Identity / bookkeeping ---
    started_at: str
    elapsed_ms: int
    inbound_id: str
    chat_channel_id: int | str
    device_id: str
    user_id: str
    character_id: str


class KnowledgeAgentGraph(NodeGroup):
    """Small LangGraph for knowledge search -> cited answer."""

    def __init__(
        self,
        *,
        workspace_path: Path,
        service: Any,
        prefs: "WorkspacePreferences",
        workspace_id: str | None = None,
    ) -> None:
        from hirocli.runtime.agent_graph.ledger import LedgerSink

        services = AgentServices(
            workspace_path=workspace_path,
            ledger_sink=LedgerSink(workspace_path),
        )
        super().__init__(services)
        self._service = service
        self._prefs = prefs
        self._workspace_id = workspace_id

    def _add_retrieval_nodes(self, graph: StateGraph) -> None:
        """Add + wire the shared retrieval prefix: START → … → build_context.

        Reused by both ``build()`` (Ask/CLI/HTTP, retrieval + answering) and
        ``build_retrieval()`` (the chat subgraph, retrieval only) so the retrieval
        logic — including the history-aware ``rewrite_query`` node — has one implementation.
        """
        graph.add_node(
            "parse_query",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/parse_query", self.parse_query),
        )
        graph.add_node(
            "rewrite_query",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/rewrite_query", self.rewrite_query),
        )
        graph.add_node(
            "graph_expand",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/graph_expand", self.graph_expand),
        )
        # --- graphiti leg: graph_expand → graph_fetch → build_context ---
        graph.add_node(
            "graph_fetch",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/graph_fetch", self.graph_fetch),
        )
        # --- flat / vector leg: build_filters → embed_query → vector_search → rerank → build_context ---
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
            "rerank",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/rerank", self.rerank),
        )
        graph.add_node(
            "build_context",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/build_context", self.build_context),
        )
        graph.add_edge(START, "parse_query")
        graph.add_edge("parse_query", "rewrite_query")
        # When rewrite decides the message needs no knowledge (small talk), skip straight to
        # build_context — bypassing build_filters / embed_query / vector_search. build_context
        # with no hits yields empty context + no_results, so downstream behaves like "no hits".
        graph.add_conditional_edges(
            "rewrite_query",
            self._route_after_rewrite,
            {"retrieve": "graph_expand", "skip": "build_context"},
        )
        # graph_expand runs unconditionally on the retrieve path; it short-circuits
        # internally when ``graph_mode=off`` (the default) or there's no query/graph.
        # Cost when off = ~zero. See ``graph_expand`` impl.
        #
        # Routing after expand splits the two eval legs:
        #   - "graphiti" WITH chunk_ids → graph_fetch (by-id passages, no hybrid)
        #   - flat, or graphiti soft-fallback (no chunk_ids) → the hybrid path
        # graphiti with no chunk_ids falls through to the hybrid path = full flat
        # search (the design's soft-fallback when the graph has nothing for the query).
        graph.add_conditional_edges(
            "graph_expand",
            self._route_after_expand,
            {"graph_only": "graph_fetch", "vector": "build_filters"},
        )
        graph.add_edge("graph_fetch", "build_context")
        graph.add_edge("build_filters", "embed_query")
        graph.add_edge("embed_query", "vector_search")
        graph.add_edge("vector_search", "rerank")
        graph.add_edge("rerank", "build_context")

    def build(self) -> CompiledStateGraph:
        """Full Ask/CLI/HTTP graph: shared retrieval prefix + cited-answer step."""
        graph = StateGraph(KnowledgeAgentState)
        self._add_retrieval_nodes(graph)
        graph.add_node(
            "call_model",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/call_model", self.call_model),
        )
        graph.add_node(
            "finalize",
            self._wrap_dynamic_node(f"{KNOWLEDGE_NODE_PREFIX}/finalize", self.finalize),
        )
        graph.add_conditional_edges(
            "build_context",
            self._route_after_context,
            {"call_model": "call_model", "finalize": "finalize"},
        )
        graph.add_edge("call_model", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def build_retrieval(self) -> CompiledStateGraph:
        """Retrieval-only subgraph for the chat agent: shared prefix → END.

        Compiled without a checkpointer (retrieval is per-turn scratch). It opens no ledger
        run of its own, so when invoked inside a chat run its node rows inherit the chat
        ``run_id`` and fold into that turn's cost (see ``ledger._resolve_ledger_identity``).
        """
        graph = StateGraph(KnowledgeAgentState)
        self._add_retrieval_nodes(graph)
        graph.add_edge("build_context", END)
        return graph.compile()

    @staticmethod
    def _route_after_rewrite(state: KnowledgeAgentState) -> str:
        # Only an explicit False skips; absent/True (rewrite off, no LLM, parse failure) retrieves.
        return "skip" if state.get("knowledge_needed") is False else "retrieve"

    @staticmethod
    def _route_after_expand(state: KnowledgeAgentState) -> str:
        return (
            "graph_only"
            if state.get("effective_leg") == RetrievalLeg.GRAPHITI.value
            else "vector"
        )

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

    @graph_logged(captures={"usage", "decision"})
    async def rewrite_query(
        self,
        state: KnowledgeAgentState,
        writer: StreamWriter | None = None,
    ) -> dict[str, Any]:
        # Opt-in LLM rewrite: normalize the query + extract literal keywords before retrieval.
        # Reuses the answering model with the dedicated ``knowledge_rewrite`` tuning profile
        # (temperature / max_tokens / thinking come from preferences, never hardcoded here).
        # Every failure path is a logged, observable fallback to the raw query — retrieval must
        # never be blocked by the rewrite step.
        if not state.get("rewrite"):
            observe(decision=("skipped", "rewrite_off"), output="rewrite disabled · raw query used")
            return {}
        normalized = state["normalized_query"]
        observe(input=f"text: {normalized.text[:200]}")
        if not normalized.text.strip():
            observe(decision=("skipped", "empty_query"), output="rewrite: <skipped empty query>")
            return {}

        resolved = resolve_knowledge_rewrite_llm(
            self._prefs,
            self.services.workspace_path,
            workspace_id=self._workspace_id,
        )
        if resolved is None:
            log.info("⚠️ knowledge.rewrite — no answering model configured · skipping rewrite")
            observe(decision=("skipped", "no_llm_configured"), output="rewrite: <skipped no model>")
            return {}

        model_id = resolved.model_id
        # Model is in the model column; show only the tuning that actually ran.
        observe(
            input=(
                f"text: {normalized.text[:180]} · temp={resolved.temperature} "
                f"max_tokens={resolved.max_tokens} thinking={resolved.thinking or 'off'}"
            )
        )
        # Cross-provider guard: only attempt structured output on models the catalog says
        # support it; otherwise the call would burn tokens and fall back every time.
        spec = get_model_catalog().get_model(model_id)
        if spec is None or "structured_output" not in spec.features:
            log.warning(
                "⚠️ knowledge.rewrite — model lacks structured_output support · skipping rewrite",
                model=model_id,
            )
            observe(
                decision=("skipped", "no_structured_output"),
                output="rewrite: <skipped unsupported model>",
            )
            return {}

        prompt = (
            self._prefs.knowledge.rewrite.prompt or ""
        ).strip() or DEFAULT_KNOWLEDGE_REWRITE_PROMPT
        # When the chat graph supplies conversation history, hand it to the model so it can
        # resolve references (pronouns, "the second one") into a standalone query. The Ask/CLI
        # path passes no history, so the human turn is just the normalized question (unchanged).
        history = (state.get("history") or "").strip()
        if history:
            human_text = (
                f"Conversation so far:\n{history}\n\nLatest user message:\n{normalized.text}"
            )
        else:
            human_text = normalized.text
        messages = [SystemMessage(content=prompt), HumanMessage(content=human_text)]
        estimate = count_tokens_approximately(messages)
        try:
            base_model = create_chat_model(
                model_id,
                workspace_path=self.services.workspace_path,
                workspace_id=self._workspace_id,
                temperature=resolved.temperature,
                max_tokens=resolved.max_tokens,
                thinking=resolved.thinking,
                num_ctx=resolved.num_ctx,
            )
            # Use the compat wrapper so DeepSeek thinking mode doesn't 400 on the forced
            # tool_choice (it falls back to json_mode). Unlike the graphiti adapter, this node
            # builds its own messages and never injects the schema, so the rewrite prompt itself
            # describes the JSON fields (see DEFAULT_KNOWLEDGE_REWRITE_PROMPT) — json_mode never
            # sees the pydantic field descriptions.
            model = with_structured_output_compat(base_model, QueryRewrite, include_raw=True)
            result = await model.ainvoke(messages)
        except Exception as exc:
            log.warning(
                "⚠️ knowledge.rewrite — model call failed, using raw query",
                error=str(exc)[:200],
                model=model_id,
                exc_info=True,
            )
            provider = model_id.split(":", 1)[0] if ":" in model_id else ""
            observe(
                usage={"provider": provider, "model": model_id},
                fail={"code": "rewrite_call_failed", "message": str(exc)},
            )
            return {}

        parsed = result.get("parsed") if isinstance(result, dict) else None
        raw = result.get("raw") if isinstance(result, dict) else None
        parsing_error = result.get("parsing_error") if isinstance(result, dict) else None

        # The call was billed whether or not parsing succeeded — record usage first so the node
        # always reports cost in graph runs, even on a parse failure.
        if raw is not None:
            usage_payload = llm_usage_payload(
                raw,
                inbound_id=str(state.get("inbound_id") or "knowledge.rewrite"),
                chat_channel_id=int(state.get("chat_channel_id") or 0),
                model_id=model_id,
                estimated_input_tokens=estimate,
            )
            provider = model_id.split(":", 1)[0] if ":" in model_id else ""
            observe(
                usage={
                    "provider": provider,
                    "model": model_id,
                    "input_tokens": int(usage_payload.get("input_tokens") or estimate or 0),
                    "output_tokens": int(usage_payload.get("output_tokens") or 0),
                    "cached_input_tokens": int(usage_payload.get("cached_input_tokens") or 0),
                    "reasoning_tokens": int(usage_payload.get("reasoning_tokens") or 0),
                }
            )
            if writer is not None:
                emit(writer, GRAPH_LLM_USAGE, usage_payload)

        # include_raw=True returns parse failures in the result dict (it does NOT raise), so we
        # must inspect parsing_error explicitly, log it with finish_reason, and fall back.
        if not isinstance(parsed, QueryRewrite):
            finish_reason = (
                str(getattr(raw, "response_metadata", {}).get("finish_reason", ""))
                if raw is not None
                else ""
            )
            log.warning(
                "⚠️ knowledge.rewrite — unparsable structured output, using raw query",
                error=str(parsing_error)[:200] if parsing_error else "no parsed object returned",
                finish_reason=finish_reason or "unknown",
                model=model_id,
            )
            observe(
                fail={
                    "code": "rewrite_unparsed",
                    "message": f"unparseable structured output (finish_reason={finish_reason or 'unknown'})",
                }
            )
            return {}

        new_text = (parsed.standalone_query or "").strip() or normalized.text
        keywords = [kw.strip() for kw in parsed.keywords if kw.strip()]
        knowledge_needed = bool(parsed.knowledge_needed)
        # L3 — query entities drive graph_expand. Strip + dedupe defensively (the LLM
        # can repeat); preserve order so deterministic rendering matches the prompt.
        entities_raw = list(parsed.entities or [])
        seen: dict[str, None] = {}
        for e in entities_raw:
            t = (e or "").strip()
            if t and t not in seen:
                seen[t] = None
        entities = list(seen)
        if knowledge_needed:
            kw = f" · kw={','.join(keywords)[:80]}" if keywords else ""
            ent = f" · ent={','.join(entities)[:80]}" if entities else ""
            observe(
                decision=("rewritten", "ok"),
                output=f"query: {new_text[:160]}{kw}{ent}",
            )
        else:
            observe(
                decision=("rewritten", "no_knowledge_needed"),
                output="knowledge_needed: false (retrieval skipped)",
            )
        return {
            "normalized_query": NormalizedQuery(
                raw=normalized.raw, text=new_text, language=normalized.language
            ),
            "rewrite_keywords": keywords,
            "query_entities": entities,
            "rewritten_query": new_text,
            "knowledge_needed": knowledge_needed,
        }

    @graph_logged(captures={"decision"})
    async def graph_expand(self, state: KnowledgeAgentState) -> dict[str, Any]:
        # L3 — Graphiti fact search → episode→chunk_id resolution. The output
        # ``graph_chunk_ids`` drives ``graph_fetch`` (by-id passages for the graphiti
        # leg) and ``graph_facts`` become the answer skeleton. SOFT FALLBACK: empty
        # result → no chunk_ids → effective_leg=FLAT → routing falls through to the
        # hybrid path = normal flat search (graph silently did nothing).
        entry = current_entry.get()  # kept: flush + sidecar need the entry object, not just previews
        intended = intended_leg(state.get("graph_mode"))
        if intended is not RetrievalLeg.GRAPHITI:
            observe(decision=("skipped", "graph_mode_off"), output="graph_mode=off · no expansion")
            return {"effective_leg": RetrievalLeg.FLAT.value}
        # Graphiti searches on the full query (hybrid over the graph) — no separate
        # entity list required (unlike the old name-resolution path).
        query = (state.get("rewritten_query") or state.get("query") or "").strip()
        if not query:
            observe(decision=("skipped", "no_query"), output="no query · no expansion")
            return {"effective_leg": RetrievalLeg.FLAT.value}

        # Graphiti fact-search → episodes→chunk_ids. The chunk_ids drive the by-id
        # passage fetch (``graph_fetch``) for the graphiti leg. SOFT FALLBACK: any
        # miss/error → empty result → effective_leg=FLAT → normal flat search.
        from hirocli.services.knowledge.graph import graphiti_db_path

        db_path = graphiti_db_path(self.services.workspace_path)
        if not db_path.exists():
            # No graph built for this workspace yet — flat search. Don't open
            # Graphiti (it would create an empty Kuzu DB as a read side effect).
            observe(decision=("skipped", "no_graph"), output="no graph built · flat search")
            return {"effective_leg": RetrievalLeg.FLAT.value}
        observe(input=f"query: {query[:80]}{'…' if len(query) > 80 else ''}")

        expansion = None
        rerank_usage = None
        capture = None
        try:
            async with graphiti_session(
                self._prefs, self.services.workspace_path, self._workspace_id
            ) as session:
                if session is None:
                    observe(
                        decision=("skipped", "backend_off_or_no_model"),
                        output="graph backend off / no model · flat search",
                    )
                    return {"effective_leg": RetrievalLeg.FLAT.value}
                temporal = (
                    state.get("graph_temporal") or self._prefs.graph.temporal_default
                )
                num_results = max(1, int(self._prefs.knowledge.retrieval.top_k))
                expansion = await session.search_chunk_ids(
                    query, num_results=num_results, temporal=temporal
                )
                rerank_usage = session.rerank_usage
                capture = session.capture
        except Exception as exc:
            log.warning(
                "⚠️ graphiti graph_expand failed · falling back to flat search",
                error=str(exc)[:200],
                exc_info=True,
            )
            observe(fail={"code": "graph_expand_failed", "message": str(exc)})
            return {"effective_leg": RetrievalLeg.FLAT.value}

        facts_preview = " | ".join(expansion.facts[:4])
        more = f" (+{len(expansion.facts) - 4})" if len(expansion.facts) > 4 else ""
        observe(
            decision=(
                "expanded" if expansion.chunk_ids else "empty",
                f"facts_{expansion.facts_used}/{expansion.facts_total}_chunks_{len(expansion.chunk_ids)}",
            ),
            output=(
                f"facts[{expansion.facts_used}]: {facts_preview}{more} · "
                f"chunks: {len(expansion.chunk_ids)}"
            ),
        )
        if entry is not None:
            # Sanctioned direct-entry use: priced rerank roll-up + per-stage trace sidecar keyed by
            # this run/step. observe() can't express these — they consume the LedgerEntry itself.
            from hirocli.services.knowledge.graph.retrieval_ledger import flush_graph_expand

            flush_graph_expand(entry, expansion, rerank_usage=rerank_usage)
            # Persist the full per-stage trace sidecar (when capture was engaged) keyed by
            # this run + step, so the retrieval-trace dialog can link it to this row.
            if capture is not None and capture.trace is not None:
                from hirocli.services.knowledge.graph.retrieval_trace import (
                    write_trace_sidecar,
                )

                write_trace_sidecar(
                    self.services.workspace_path,
                    run_id=entry.run_id,
                    step_index=entry.step_index,
                    trace=capture.trace,
                )
        # graph_facts feed the answer skeleton for the graphiti leg; graph_chunk_ids
        # drive the by-id passage fetch (graph_fetch).
        resolved = effective_leg(intended, chunk_ids=expansion.chunk_ids)
        return {
            "graph_chunk_ids": list(expansion.chunk_ids),
            "graph_facts": list(expansion.facts),
            "effective_leg": resolved.value,
        }

    @graph_logged(captures={"decision"})
    async def graph_fetch(self, state: KnowledgeAgentState) -> dict[str, Any]:
        # "graphiti" leg — the graph alone decides: fetch the verbatim episode
        # chunks for the fact-supporting chunk_ids directly by id (graph-ranked
        # order, no query hybrid / no min_score drop). Empty-text points (chunk
        # not in Qdrant) are skipped. Pairs with the facts injected in build_context.
        chunk_ids = state.get("graph_chunk_ids") or []
        if not chunk_ids:
            observe(
                decision=("skipped", "no_chunk_ids"),
                output="graphiti leg · no chunk_ids · facts-only",
            )
            return {"hits": []}
        observe(input=f"chunk_ids: {len(chunk_ids)} (graph-ranked, by-id)")
        try:
            hits = await self._service.fetch_hits_by_point_ids(chunk_ids)
        except Exception as exc:
            log.warning(
                "⚠️ graphiti graph_fetch failed · falling back to facts-only context",
                error=str(exc)[:200],
                exc_info=True,
            )
            observe(fail={"code": "graph_fetch_failed", "message": str(exc)})
            return {"hits": []}
        rows = knowledge_results_rows(hits)
        head = f"passages {len(hits)} of {len(chunk_ids)} (by-id)"
        observe(
            decision=("ok" if hits else "empty", f"passages_{len(hits)}"),
            output=f"{head} · {rows}" if rows else head,
            output_max_len=KNOWLEDGE_PREVIEW_MAX,
        )
        # reranked=False so build_context tags relevance as ordinal (graph-ranked).
        return {"hits": hits, "reranked": False}

    def build_filters(self, state: KnowledgeAgentState) -> dict[str, Any]:
        # The hybrid path only runs for the flat leg (and the graphiti soft-fallback
        # when the graph found no chunk_ids); neither carries graph_chunk_ids, so
        # there is nothing graph-specific to fold in. (The removed "mix" leg was the
        # only path that restricted the hybrid to the graph's chunk_ids.)
        merged = dict(state.get("filters") or {})
        return {"qdrant_filter": build_qdrant_filter(merged)}

    @graph_logged(captures={"usage", "decision"})
    async def embed_query(self, state: KnowledgeAgentState) -> dict[str, Any]:
        normalized = state["normalized_query"]
        embedding_model = self._prefs.knowledge.default_embedding_model_resolved
        hybrid = self._prefs.knowledge.retrieval.hybrid
        sparse_model = self._prefs.knowledge.retrieval.sparse_model
        # Put the embedding model in the model column and an estimated input-token count so the
        # ledger prices it (gross list price; embedding pricing is input-only). Local/free
        # embedders aren't catalogued → cost stays blank.
        provider = embedding_model.split(":", 1)[0] if ":" in embedding_model else ""
        observe(
            usage={
                "provider": provider,
                "model": embedding_model,
                "input_tokens": estimate_text_tokens(normalized.text),
            },
            input=(
                (f"sparse: {sparse_model} · " if hybrid else "")
                + f"text: {normalized.text[:180]}"
            ),
        )
        try:
            vector = await self._service.embed_query(normalized.text)
        except Exception as exc:
            # Record a rich error row, then propagate so knowledge_retrieve degrades gracefully.
            observe(fail={"code": "embed_failed", "message": str(exc)})
            raise
        if not _is_valid_vector(vector):
            # Garbage embedding (empty / non-finite) — flag it and short-circuit to 0 hits instead of
            # silently searching with a useless vector.
            length = len(vector) if hasattr(vector, "__len__") else 0
            observe(
                fail={
                    "code": "invalid_embedding",
                    "message": f"embedder returned invalid vector (len={length})",
                }
            )
            return {"query_vector": []}
        out: dict[str, Any] = {"query_vector": vector}
        # Only pay for the BM25 query embed when hybrid is enabled. Append rewrite keywords
        # (literal proper nouns/identifiers) so the sparse branch keeps its exact-match signal.
        sparse = None
        if hybrid:
            keywords = state.get("rewrite_keywords") or []
            sparse_text = (
                f"{normalized.text} {' '.join(keywords)}".strip() if keywords else normalized.text
            )
            sparse = await self._service.embed_query_sparse(sparse_text)
            out["query_sparse_vector"] = sparse
        # Was an empty row before; report vector dim + whether the sparse branch ran so the step is
        # not a black box.
        dim = len(vector) if hasattr(vector, "__len__") else 0
        observe(
            decision=("embedded", f"dim_{dim}"),
            output=f"embedded: dim={dim}; sparse={'yes' if sparse is not None else 'no'}",
        )
        return out

    @graph_logged(captures={"decision"})
    async def vector_search(self, state: KnowledgeAgentState) -> dict[str, Any]:
        retrieval = self._prefs.knowledge.retrieval
        top_k = int(state.get("top_k") or retrieval.top_k)
        min_score = float(
            state["min_score"] if state.get("min_score") is not None else retrieval.min_score
        )
        nq = state.get("normalized_query")
        query_text = nq.text if nq is not None else str(state.get("query") or "")
        # Surface the query text + effective knobs so a low/zero hit count is interpretable
        # (wrong query? min_score too high? filtered? hybrid off?) instead of a bare "hits: 0".
        observe(
            input=(
                f"q: {query_text[:80]} · top_k={top_k} min_score={min_score:.2f} "
                f"prefetch/branch={retrieval.prefetch_limit} "
                f"hybrid={'on' if retrieval.hybrid else 'off'} "
                f"filter={'yes' if state.get('qdrant_filter') else 'none'}"
            )
        )
        vector = state.get("query_vector") or []
        if not vector:
            observe(decision=("empty", "no_query_vector"), output="hits 0; no_query_vector")
            return {"hits": []}
        hits = await self._service.vector_search_by_vector(
            vector,
            state.get("query_sparse_vector"),
            top_k=top_k,
            min_score=min_score,
            prefetch_limit=retrieval.prefetch_limit,
            hybrid=retrieval.hybrid,
            explain=bool(state.get("explain")),
            qdrant_filter=state.get("qdrant_filter"),
        )
        source = "rrf" if retrieval.hybrid else "cosine"
        rows = knowledge_results_rows(hits)
        head = f"hits {len(hits)} ({source})"
        observe(
            decision=("ok", f"hits_{len(hits)}"),
            output=f"{head} · {rows}" if rows else head,
            output_max_len=KNOWLEDGE_PREVIEW_MAX,
        )
        return {"hits": hits}

    @graph_logged(captures={"usage", "decision"})
    async def rerank(self, state: KnowledgeAgentState) -> dict[str, Any]:
        # Opt-in cross-encoder reranking over the retrieved candidates (precision step).
        # Prefs-only, default off. Fails safe: any error logs and returns {} so the fused
        # retrieval order is kept — reranking never blocks an answer.
        reranker = self._prefs.knowledge.retrieval.reranker
        hits = state.get("hits") or []
        # Record WHY we skipped instead of writing a blank row — a node that ran should never be a
        # black box.
        if not reranker.enabled or not reranker.model_id:
            reason = "disabled" if not reranker.enabled else "no_model"
            observe(
                decision=("skipped", reason),
                output=f"reranker off ({reason}) · retrieval order kept",
            )
            return {}
        if not hits:
            observe(decision=("skipped", "no_candidates"), output="no candidates to rerank")
            return {}
        provider = reranker.model_id.split(":", 1)[0] if ":" in reranker.model_id else ""
        normalized = state["normalized_query"]
        # Estimate billed work (gross list price; free tiers ignored). Voyage-style processed
        # tokens = query_tokens × #candidates + sum(candidate doc tokens); Cohere prices per search
        # unit — the cost estimator reads the model's kind/pricing and applies the right shape.
        processed_tokens = estimate_text_tokens(normalized.text) * len(hits) + sum(
            estimate_text_tokens(getattr(hit, "text", "") or "") for hit in hits
        )
        observe(
            usage={
                "provider": provider,
                "model": reranker.model_id,
                "input_tokens": processed_tokens,
            },
            input=f"candidates: {len(hits)} · top_n: {reranker.top_n}",
        )
        try:
            reranked = await self._service.rerank_hits(
                normalized.text,
                hits,
                model_id=reranker.model_id,
                top_n=reranker.top_n,
                device=reranker.device,
                workspace_id=self._workspace_id,
            )
        except Exception as exc:
            log.warning(
                "⚠️ knowledge.rerank — failed, using retrieval order",
                error=str(exc)[:200],
                model=reranker.model_id,
                exc_info=True,
            )
            observe(fail={"code": "rerank_failed", "message": str(exc)})
            return {}
        rows = knowledge_results_rows(reranked)
        head = f"reranked {len(reranked)} of {len(hits)}"
        observe(
            decision=("ok", f"reranked_{len(reranked)}"),
            output=f"{head} · {rows}" if rows else head,
            output_max_len=KNOWLEDGE_PREVIEW_MAX,
        )
        return {"hits": reranked, "reranked": True}

    @graph_logged(captures={"decision"})
    async def build_context(self, state: KnowledgeAgentState) -> dict[str, Any]:
        from hirocli.services.knowledge.converters import source_from_hit

        # matched_terms is a human-eval hint, computed only in opt-in explain mode.
        explain = bool(state.get("explain"))
        normalized = state.get("normalized_query")
        query_text = normalized.text if normalized is not None else str(state.get("query", ""))
        hits = state.get("hits") or []
        # Graph legs only: stamp each passage's episode event date (valid_at) so the answer
        # model can resolve relative dates in the body ("today") to an absolute date. The flat
        # leg stays graph-free (its purpose is to isolate the no-graph baseline), so no fetch.
        valid_at_by_id = await self._chunk_dates(state, hits)
        # Unified score contract: when the rerank node ran, sources carry the reranker's
        # normalized relevance (set on the hits). Otherwise relevance is the retrieval score
        # min-max normalized within this result set (ordinal, not calibrated) — tagged so chat
        # fusion knows the provenance. score_source is "rrf" under hybrid, else "cosine".
        reranked = bool(state.get("reranked"))
        score_source = (
            "reranker"
            if reranked
            else ("rrf" if self._prefs.knowledge.retrieval.hybrid else "cosine")
        )
        fallback_relevances = (
            None if reranked else _minmax_relevances([float(hit.score) for hit in hits])
        )
        sources = []
        for index, hit in enumerate(hits, start=1):
            terms = matched_query_terms(query_text, hit.text) if explain else None
            relevance = None if reranked else fallback_relevances[index - 1]
            sources.append(
                source_from_hit(
                    index,
                    hit,
                    matched_terms=terms,
                    relevance=relevance,
                    score_source=score_source,
                    valid_at=valid_at_by_id.get(hit.point_id),
                )
            )
        # Graph legs prepend the fact statements as an answer skeleton (G4 / §5.5) — this is
        # what carries the temporal supersession the passages alone can't express. Facts count
        # as context too, so a graphiti leg with thin passages still answers (not no_results).
        facts_block = graphiti_facts_block(state.get("graph_facts") or [])
        facts = [f for f in (state.get("graph_facts") or []) if (f or "").strip()]
        context = build_context(sources)
        if facts_block:
            context = f"{facts_block}\n\n{context}" if context else facts_block
        no_results = not (sources or facts)
        # Surface the assembled prompt skeleton: dated passages (the valid_at that lets the
        # model resolve "today") + the fact-skeleton count. This is the only node that holds
        # per-passage dates, so without it they're invisible in the ledger.
        dated = sum(1 for s in sources if getattr(s, "valid_at", None))
        rows = knowledge_results_rows(sources)
        head = f"context · sources={len(sources)} (dated {dated}) · facts={len(facts)}"
        observe(
            decision="no_results" if no_results else "ok",
            output=f"{head} · {rows}" if rows else head,
            output_max_len=KNOWLEDGE_PREVIEW_MAX,
        )
        return {
            "sources": sources,
            "context": context,
            "no_results": no_results,
        }

    async def _chunk_dates(
        self, state: KnowledgeAgentState, hits: list[Any]
    ) -> dict[str, str]:
        """Map hit point_id → episode event date (YYYY-MM-DD) for the graph legs.

        ``valid_at`` lives on the Graphiti episode (not the Qdrant payload), so it needs a
        graph read. Scoped to the graph legs so the flat leg stays a true no-graph baseline;
        best-effort — any miss (no graph / read error) yields ``{}`` and dateless passages."""
        if state.get("effective_leg") != RetrievalLeg.GRAPHITI.value or not hits:
            return {}
        from hirocli.services.knowledge.graph.graphiti_service import (
            graphiti_db_path,
            read_episode_valid_at,
        )

        db_path = graphiti_db_path(self.services.workspace_path)
        if not db_path.exists():
            return {}
        point_ids = [h.point_id for h in hits if getattr(h, "point_id", "")]
        try:
            raw = await read_episode_valid_at(db_path, point_ids)
        except Exception as exc:
            # Graph DB read — non-fatal provenance; log and answer without passage dates.
            log.warning(
                "⚠️ knowledge — passage valid_at lookup failed · count=%d",
                len(point_ids),
                error=str(exc)[:200],
                exc_info=True,
            )
            return {}
        # read_episode_valid_at returns full ISO (or None); the prompt wants date-only.
        return {pid: iso[:10] for pid, iso in raw.items() if iso}

    @graph_logged(captures={"usage", "decision"})
    async def call_model(
        self,
        state: KnowledgeAgentState,
        writer: StreamWriter | None = None,
    ) -> dict[str, Any]:
        resolved = resolve_knowledge_answering_llm(
            self._prefs,
            self.services.workspace_path,
            workspace_id=self._workspace_id,
        )
        normalized = state["normalized_query"]
        answering = self._prefs.knowledge.answering
        # Show the answering config that actually ran: language policy, citation toggle, and the
        # resolved tuning (temp/max_tokens/thinking) — not just the question text.
        # Model is in the model column; show the answering config + tuning that ran, not the id.
        tuning = (
            f" · temp={resolved.temperature} max_tokens={resolved.max_tokens} "
            f"thinking={resolved.thinking or 'off'}"
            if resolved is not None
            else ""
        )
        observe(
            input=(
                f"text: {normalized.text[:180]} · lang={answering.language_policy} "
                f"cite={answering.cite_sources}{tuning}"
            )
        )
        if resolved is None:
            answer = self._fallback_answer(state)
            observe(decision=("skipped", "no_llm_configured"), output=f"answer: {answer[:200]}")
            return {
                "answer": answer,
                "model_id": None,
                "usage": {},
            }
        model_id = resolved.model_id
        try:
            model = create_chat_model(
                model_id,
                workspace_path=self.services.workspace_path,
                workspace_id=self._workspace_id,
                temperature=resolved.temperature,
                max_tokens=resolved.max_tokens,
                thinking=resolved.thinking,
                num_ctx=resolved.num_ctx,
            )
        except Exception as exc:
            log.error("knowledge.answer model creation failed", error=str(exc), exc_info=True)
            answer = self._fallback_answer(state)
            provider = model_id.split(":", 1)[0] if ":" in model_id else ""
            observe(
                usage={"provider": provider, "model": model_id},
                fail={"code": "model_create_failed", "message": str(exc)},
            )
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
            provider = model_id.split(":", 1)[0] if ":" in model_id else ""
            observe(
                usage={"provider": provider, "model": model_id},
                fail={"code": "model_call_failed", "message": str(exc)},
            )
            return {"answer": answer, "model_id": model_id, "usage": {}}
        usage_payload = llm_usage_payload(
            response,
            inbound_id=str(state.get("inbound_id") or "knowledge.answer"),
            chat_channel_id=int(state.get("chat_channel_id") or 0),
            model_id=model_id,
            estimated_input_tokens=estimate,
        )
        answer = normalize_reply_content(getattr(response, "content", ""))
        provider = model_id.split(":", 1)[0] if ":" in model_id else ""
        observe(
            usage={
                "provider": provider,
                "model": model_id,
                "input_tokens": int(usage_payload.get("input_tokens") or estimate or 0),
                "output_tokens": int(usage_payload.get("output_tokens") or 0),
                "cached_input_tokens": int(usage_payload.get("cached_input_tokens") or 0),
                "reasoning_tokens": int(usage_payload.get("reasoning_tokens") or 0),
            },
            decision=("text_reply", "ok"),
            output=f"answer: {answer[:200]}" if answer.strip() else "answer: <empty>",
        )
        if writer is not None:
            emit(writer, GRAPH_LLM_USAGE, usage_payload)
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
        sources = len(state.get("sources") or [])
        if state.get("no_results"):
            observe(
                decision=("empty", "no_results"),
                output=f"no_results · sources=0 · elapsed={elapsed_ms}ms",
            )
        else:
            # Don't repeat the answer (it's already on call_model) — show the terminal run
            # summary that only finalize knows: source count + answer size + total elapsed.
            answer = str(state.get("answer") or "")
            observe(
                decision=("completed", "knowledge_answer"),
                output=(
                    f"answered · sources={sources} · answer_chars={len(answer)} · "
                    f"elapsed={elapsed_ms}ms"
                ),
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
        # Base instruction now comes from the editable answering pref (blank → relaxed default that
        # allows partial answers); the citation + language clauses below are still appended at runtime.
        base = (
            self._prefs.knowledge.answering.prompt or ""
        ).strip() or DEFAULT_KNOWLEDGE_ANSWERING_PROMPT
        parts = [base]
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
