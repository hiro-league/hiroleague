"""Answer-side node group for the knowledge graph (review §1.6).

Two nodes that turn an assembled context into a cited reply:

    call_model → finalize

The post-context router ``route_after_context`` lives here too — it skips the model
when ``build_context`` flagged ``no_results`` and routes straight to ``finalize`` for
the canned fallback. The retrieval-side routers are on ``KnowledgeRetrievalNodes``.

Mounted only by ``KnowledgeAgentGraph.build`` (the full Ask/CLI/HTTP graph); the
chat-side retrieval subgraph (``build_retrieval``) skips this group entirely.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from hiro_commons.log import Logger
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.types import StreamWriter

from hirocli.domain.model_factory import create_chat_model
from hirocli.domain.preferences import resolve_knowledge_answering_llm
from hirocli.runtime.agent_graph.events import GRAPH_LLM_USAGE
from hirocli.runtime.agent_graph.graph_kit import (
    emit,
    llm_usage_payload,
    normalize_reply_content,
)
from hirocli.runtime.agent_graph.ledger import graph_logged, observe
from hirocli.runtime.agent_graph.node_group import NodeGroup
from hirocli.runtime.agent_graph.services import AgentServices

from .config import KnowledgeGraphConfig
from .prompts import fallback_answer, system_prompt
from .state import KnowledgeAgentState

log = Logger.get("SVC.KNOWLEDGE.GRAPH")


class KnowledgeAnswerNodes(NodeGroup):
    """Cited-answer + finalize — the answer half of the knowledge graph."""

    _ledger_label_prefix = "knowledge"

    def __init__(self, services: AgentServices, config: KnowledgeGraphConfig) -> None:
        super().__init__(services)
        self._service = config.service  # unused here; kept for ctor symmetry with retrieval
        self._prefs = config.prefs
        self._workspace_id = config.workspace_id

    @staticmethod
    def route_after_context(state: KnowledgeAgentState) -> str:
        if state.get("no_results"):
            return "finalize"
        return "call_model"

    @graph_logged(captures={"usage", "decision"})
    async def call_model_node(
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
            answer = fallback_answer(
                prefs=self._prefs,
                normalized=normalized,
                sources=state.get("sources") or [],
                query=state.get("query", ""),
            )
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
            answer = fallback_answer(
                prefs=self._prefs,
                normalized=normalized,
                sources=state.get("sources") or [],
                query=state.get("query", ""),
            )
            provider = model_id.split(":", 1)[0] if ":" in model_id else ""
            observe(
                usage={"provider": provider, "model": model_id},
                fail={"code": "model_create_failed", "message": str(exc)},
            )
            return {"answer": answer, "model_id": model_id, "usage": {}}
        messages = [
            SystemMessage(content=system_prompt(prefs=self._prefs, normalized=normalized)),
            HumanMessage(content=f"Question:\n{normalized.text}\n\nContext:\n{state.get('context', '')}"),
        ]
        estimate = count_tokens_approximately(messages)
        try:
            response = await model.ainvoke(messages)
        except Exception as exc:
            log.error("knowledge.answer model call failed", error=str(exc), exc_info=True)
            answer = fallback_answer(
                prefs=self._prefs,
                normalized=normalized,
                sources=state.get("sources") or [],
                query=state.get("query", ""),
            )
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
    def finalize_node(self, state: KnowledgeAgentState) -> dict[str, Any]:
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
