"""Retrieval-side node group for the knowledge graph (review §1.6).

Nine nodes that take a normalized query through the retrieval pipeline:

    parse_query → rewrite_query → graph_expand → graph_fetch → build_filters
                                                            → embed_query
                                                            → vector_search
                                                            → rerank
                                                            → build_context

Routers ``route_after_rewrite`` and ``route_after_expand`` live here too — they switch
on retrieval-side state (``knowledge_needed``, ``effective_leg``). The answer-side
routing decision (``route_after_context``) belongs to ``KnowledgeAnswerNodes``.

The retrieval-only subgraph (``KnowledgeAgentGraph.build_retrieval``) mounts ONLY this
group; the full Ask/CLI/HTTP graph mounts this plus ``KnowledgeAnswerNodes``.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from hiro_commons.log import Logger
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.types import StreamWriter

from hirocli.domain.model_factory import create_chat_model, with_structured_output_compat
from hirocli.domain.preferences import (
    DEFAULT_KNOWLEDGE_REWRITE_PROMPT,
    resolve_knowledge_embedder_model,
    resolve_knowledge_reranker_model,
)
from hirocli.runtime.agent_graph.events import GRAPH_LLM_USAGE
from hirocli.runtime.agent_graph.graph_kit import (
    KNOWLEDGE_PREVIEW_MAX,
    emit,
    estimate_text_tokens,
    knowledge_results_rows,
)
from hirocli.runtime.agent_graph.ledger import current_entry, graph_logged, observe
from hirocli.runtime.agent_graph.node_group import NodeGroup
from hirocli.runtime.agent_graph.services import AgentServices
from hirocli.services.knowledge.constants import DEFAULT_SPARSE_MODEL
from hirocli.services.knowledge.graph.graphiti_session import graphiti_session

from .config import KnowledgeGraphConfig
from .helpers import (
    QueryRewrite,
    build_context,
    build_qdrant_filter,
    matched_query_terms,
    minmax_relevances,
    normalize_query,
)
from .legs import RetrievalLeg, effective_leg, graphiti_facts_block, intended_leg
from .rewrite_support import (
    RewriteModelSkip,
    parse_rewrite_result,
    resolve_rewrite_model,
    rewrite_state_update,
)
from .state import KnowledgeAgentState

log = Logger.get("SVC.KNOWLEDGE.GRAPH")


def _is_valid_vector(vector: Any) -> bool:
    """A usable dense query vector is non-empty and finite; an empty/NaN vector means the embedder
    returned garbage and retrieval should not proceed on it."""
    try:
        if not len(vector):
            return False
        return math.isfinite(float(vector[0]))
    except (TypeError, ValueError, IndexError):
        return False


class KnowledgeRetrievalNodes(NodeGroup):
    """Retrieval pipeline — parse → rewrite → graph/vector → context."""

    _ledger_label_prefix = "knowledge"

    def __init__(self, services: AgentServices, config: KnowledgeGraphConfig) -> None:
        super().__init__(services)
        self._service = config.service
        self._prefs = config.prefs
        self._workspace_id = config.workspace_id

    @staticmethod
    def route_after_rewrite(state: KnowledgeAgentState) -> str:
        # Only an explicit False skips; absent/True (rewrite off, no LLM, parse failure) retrieves.
        return "skip" if state.get("knowledge_needed") is False else "retrieve"

    @staticmethod
    def route_after_expand(state: KnowledgeAgentState) -> str:
        return (
            "graph_only"
            if state.get("effective_leg") == RetrievalLeg.GRAPHITI.value
            else "vector"
        )

    def parse_query_node(self, state: KnowledgeAgentState) -> dict[str, Any]:
        normalized = normalize_query(state.get("query", ""))
        return {
            "normalized_query": normalized,
            "started_at": dt.datetime.now(dt.UTC).isoformat(),
        }

    @graph_logged(captures={"usage", "decision"}, on_error="degrade")
    async def rewrite_query_node(
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

        resolution = resolve_rewrite_model(
            self._prefs,
            self.services.workspace_path,
            workspace_id=self._workspace_id,
        )
        if isinstance(resolution, RewriteModelSkip):
            if resolution.reason == "no_llm_configured":
                log.info("⚠️ knowledge.rewrite — no answering model configured · skipping rewrite")
                observe(
                    decision=("skipped", "no_llm_configured"),
                    output="rewrite: <skipped no model>",
                )
            else:
                log.warning(
                    "⚠️ knowledge.rewrite — model lacks structured_output support · skipping rewrite",
                    model=resolution.model_id,
                )
                observe(
                    decision=("skipped", "no_structured_output"),
                    output="rewrite: <skipped unsupported model>",
                )
            return {}

        resolved = resolution.resolved
        model_id = resolution.model_id
        # Model is in the model column; show only the tuning that actually ran.
        observe(
            input=(
                f"text: {normalized.text[:180]} · temp={resolved.temperature} "
                f"max_tokens={resolved.max_tokens} thinking={resolved.thinking or 'off'}"
            )
        )
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

        parsed_outcome = parse_rewrite_result(
            result,
            model_id=model_id,
            inbound_id=str(state.get("inbound_id") or "knowledge.rewrite"),
            chat_channel_id=int(state.get("chat_channel_id") or 0),
            estimated_input_tokens=estimate,
        )
        if parsed_outcome.usage_payload is not None:
            provider = model_id.split(":", 1)[0] if ":" in model_id else ""
            usage_payload = parsed_outcome.usage_payload
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

        if parsed_outcome.fail is not None:
            log.warning(
                "⚠️ knowledge.rewrite — unparsable structured output, using raw query",
                error=str(parsed_outcome.parsing_error)[:200]
                if parsed_outcome.parsing_error
                else "no parsed object returned",
                finish_reason=parsed_outcome.finish_reason or "unknown",
                model=model_id,
            )
            observe(fail=parsed_outcome.fail)
            return {}

        assert parsed_outcome.parsed is not None
        parsed = parsed_outcome.parsed
        update = rewrite_state_update(parsed, normalized)
        knowledge_needed = bool(update["knowledge_needed"])
        new_text = update["rewritten_query"]
        keywords = update["rewrite_keywords"]
        entities = update["query_entities"]
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
        return update

    @graph_logged(captures={"decision"}, on_error="degrade")
    async def graph_expand_node(self, state: KnowledgeAgentState) -> dict[str, Any]:
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

    @graph_logged(captures={"decision"}, on_error="degrade")
    async def graph_fetch_node(self, state: KnowledgeAgentState) -> dict[str, Any]:
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

    def build_filters_node(self, state: KnowledgeAgentState) -> dict[str, Any]:
        # The hybrid path only runs for the flat leg (and the graphiti soft-fallback
        # when the graph found no chunk_ids); neither carries graph_chunk_ids, so
        # there is nothing graph-specific to fold in. (The removed "mix" leg was the
        # only path that restricted the hybrid to the graph's chunk_ids.)
        merged = dict(state.get("filters") or {})
        return {"qdrant_filter": build_qdrant_filter(merged)}

    # mixed: re-raises on embed-call failure (``embed_failed``, retrieval can't continue without
    # an embedding) but degrades on a garbage vector (``invalid_embedding`` → ``query_vector: []``).
    @graph_logged(captures={"usage", "decision"}, on_error="mixed")
    async def embed_query_node(self, state: KnowledgeAgentState) -> dict[str, Any]:
        normalized = state["normalized_query"]
        # Effective knowledge embedder (override → workspace default); None when unconfigured —
        # the embed below then fails fast (no silent model). For the ledger model column only.
        embedding_model = resolve_knowledge_embedder_model(self._prefs)
        hybrid = self._prefs.knowledge.retrieval.hybrid
        # Sparse model is a fixed constant (no longer a preference) — for the ledger label only.
        sparse_model = DEFAULT_SPARSE_MODEL
        # Put the embedding model in the model column and an estimated input-token count so the
        # ledger prices it (gross list price; embedding pricing is input-only). Local/free
        # embedders aren't catalogued → cost stays blank.
        provider = (
            embedding_model.split(":", 1)[0] if embedding_model and ":" in embedding_model else ""
        )
        observe(
            usage={
                "provider": provider,
                "model": embedding_model or "",
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

    @graph_logged(captures={"decision"}, on_error="raise")
    async def vector_search_node(self, state: KnowledgeAgentState) -> dict[str, Any]:
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

    @graph_logged(captures={"usage", "decision"}, on_error="degrade")
    async def rerank_node(self, state: KnowledgeAgentState) -> dict[str, Any]:
        # Opt-in cross-encoder reranking over the retrieved candidates (precision step).
        # Prefs-only, default off. Fails safe: any error logs and returns {} so the fused
        # retrieval order is kept — reranking never blocks an answer.
        reranker = self._prefs.knowledge.retrieval.reranker
        # Resolve the effective model: the knowledge override, else the workspace default
        # reranker (llm.default_reranker). None = nothing configured anywhere → skip.
        model_id = resolve_knowledge_reranker_model(self._prefs)
        hits = state.get("hits") or []
        # Record WHY we skipped instead of writing a blank row — a node that ran should never be a
        # black box.
        if not reranker.enabled or not model_id:
            reason = "disabled" if not reranker.enabled else "no_model"
            observe(
                decision=("skipped", reason),
                output=f"reranker off ({reason}) · retrieval order kept",
            )
            return {}
        if not hits:
            observe(decision=("skipped", "no_candidates"), output="no candidates to rerank")
            return {}
        provider = model_id.split(":", 1)[0] if ":" in model_id else ""
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
                "model": model_id,
                "input_tokens": processed_tokens,
            },
            input=f"candidates: {len(hits)} · top_n: {reranker.top_n}",
        )
        try:
            reranked = await self._service.rerank_hits(
                normalized.text,
                hits,
                model_id=model_id,
                top_n=reranker.top_n,
                device=reranker.device,
                workspace_id=self._workspace_id,
            )
        except Exception as exc:
            log.warning(
                "⚠️ knowledge.rerank — failed, using retrieval order",
                error=str(exc)[:200],
                model=model_id,
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

    @graph_logged(captures={"decision"}, on_error="raise")
    async def build_context_node(self, state: KnowledgeAgentState) -> dict[str, Any]:
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
            None if reranked else minmax_relevances([float(hit.score) for hit in hits])
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
