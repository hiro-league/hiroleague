"""Knowledge-fanout node group — chat-side branch into the knowledge retrieval subgraph.

Split out of the old monolithic ``ConversationNodes`` (review §1.5).

- ``knowledge_fanout`` (router) — fan trim_history out to memory_search ∥ knowledge_retrieve
- ``knowledge_retrieve`` — invoke the wired knowledge subgraph, map context/sources

The knowledge subgraph itself lives at ``services.knowledge.agent.graph`` and is compiled
once per chat graph build; this group is the chat-side entry point.
"""

from __future__ import annotations

from typing import Any

from hiro_commons.log import Logger
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.types import StreamWriter

from ..graph_kit import (
    KNOWLEDGE_PREVIEW_MAX,
    knowledge_results_rows,
    normalize_reply_content,
)
from ..ledger import graph_logged, observe, substep_scope
from ..node_group import NodeGroup
from ..state import GraphState

log = Logger.get("AGENT.GRAPH")


def _format_history(messages: list[AnyMessage], *, limit: int = 6) -> str:
    """Format the last ``limit`` prior turns as 'Role: text' lines for the knowledge rewrite node.

    Called at ``knowledge_retrieve`` time, before the new user turn is appended, so this is the
    prior conversation only — exactly the context needed to resolve references in the query.
    """
    lines: list[str] = []
    for message in messages[-limit:]:
        if isinstance(message, HumanMessage):
            role = "User"
        elif isinstance(message, AIMessage):
            role = "Assistant"
        else:
            continue
        text = normalize_reply_content(message.content).strip()
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


class KnowledgeFanoutNodes(NodeGroup):
    """Chat-side knowledge entry — constructed from ``AgentServices`` only."""

    def is_active(self, label: str) -> bool:
        """``knowledge_retrieve`` is only registered when a knowledge subgraph is mounted.

        Returning False here drops the node from ``registered_nodes()`` *and* from the
        builder's conditional path-map — chat then wires ``trim_history`` straight to
        ``memory_search`` with no fan-out.
        """
        if label == "knowledge_retrieve":
            return self.services.knowledge_subgraph is not None
        return True

    def knowledge_fanout(self, state: GraphState) -> list[str]:
        """Fan out from ``trim_history`` to the parallel context branches.

        ``memory_search`` always runs; ``knowledge_retrieve`` is added only when a knowledge
        subgraph is wired and the per-message toggle is on (default on). Both join at
        ``context_build``.
        """
        targets = ["memory_search"]
        if self.services.knowledge_subgraph is not None and bool(
            state.get("knowledge_enabled", True)
        ):
            targets.append("knowledge_retrieve")
        return targets

    @graph_logged(captures={"decision"})
    async def knowledge_retrieve_node(
        self, state: GraphState, writer: StreamWriter
    ) -> dict[str, Any]:
        """Run the knowledge retrieval subgraph and map context + sources into chat state.

        Invoked with no ledger run of its own, so its ``knowledge/*`` node rows fold into the
        chat turn. Any failure degrades gracefully — the turn still answers without knowledge.
        """
        if self.services.knowledge_subgraph is None:
            observe(decision=("skipped", "no_subgraph"), output="sources: 0; no_subgraph")
            return {}
        user_text = (state.get("user_text") or "").strip()
        if not user_text:
            observe(decision=("empty", "no_user_text"), output="sources: 0; no_user_text")
            return {}
        observe(input=f"query: {user_text[:160]}")

        retrieval = self.prefs.current.knowledge.retrieval
        sub_input: dict[str, Any] = {
            "query": user_text,
            "history": _format_history(list(state.get("messages") or [])),
            "rewrite": True,
            "filters": self._knowledge_scope_filters(state),
            "top_k": retrieval.top_k,
            "min_score": retrieval.min_score,
            "inbound_id": state.get("inbound_id", ""),
            "chat_channel_id": state.get("chat_channel_id", 0),
            "character_id": state.get("character_id", ""),
            "user_id": str(state.get("data_user_id") or ""),
        }
        # Number the retrieval subgraph's ``knowledge/*`` rows as sub-steps of this node (e.g. ``4.1``)
        # so they sort under it in the ledger instead of restarting their own step counter.
        with substep_scope():
            try:
                out = await self.services.knowledge_subgraph.ainvoke(sub_input)
            except Exception as exc:
                log.warning(
                    "⚠️ knowledge_retrieve failed - %s",
                    state.get("inbound_id", "?"),
                    error=str(exc),
                    exc_info=True,
                )
                observe(
                    fail={
                        "code": "knowledge_retrieve_failed",
                        "message": str(exc),
                        "decision": "failed",
                    }
                )
                return {}

        sources = list(out.get("sources") or [])
        context = out.get("context") or ""
        if sources:
            score_source = str(getattr(sources[0], "score_source", "") or "").strip()
            head = f"{len(sources)} src" + (f" ({score_source})" if score_source else "")
            observe(
                decision=("retrieved", str(len(sources))),
                output=f"{head} · {knowledge_results_rows(sources)}",
                output_max_len=KNOWLEDGE_PREVIEW_MAX,
            )
        else:
            observe(decision=("empty", str(len(sources))), output="0 src")
        return {"knowledge_context": context, "knowledge_sources": sources}

    def _knowledge_scope_filters(self, state: GraphState) -> dict[str, Any]:
        """Owner/category scope for chat retrieval, derived server-side (never from the LLM).

        v1: all owners visible (system + character + user) → no filter. Tightening to a
        per-character/per-user policy is a later step.
        """
        return {}
