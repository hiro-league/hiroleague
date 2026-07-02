"""Context node group — history trim, user-turn append, and per-turn context assembly.

Split out of the old monolithic ``ConversationNodes`` (review §1.5). Owns the three
stateless nodes that prepare the chat-history side of the turn:

- ``trim_history`` — bound the chat suffix to ``chat.max_messages``
- ``context_build`` — append the new user turn to the trimmed history
- ``compose_context`` — assemble the ephemeral ``turn_context`` (memory + knowledge + citation)
  injected at ``call_model`` time

Reads ``messages``, ``retrieved_memories``, ``knowledge_sources``, ``user_text`` from state.
Writes ``messages`` (RemoveAll + trimmed) and ``turn_context``.
"""

from __future__ import annotations

from typing import Any

from hiro_commons.log import Logger
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import StreamWriter

from ..context_assembly import (
    ContextAssembler,
    citation_block,
    instructions_block,
    knowledge_block,
    memory_block,
)
from ..ledger import graph_logged, observe
from ..node_group import NodeGroup
from ..state import GraphState

log = Logger.get("AGENT.GRAPH")


def _trim_chat_history(messages: list[AnyMessage], limit: int) -> list[AnyMessage]:
    """Return a bounded chat suffix that does not start inside a tool exchange."""
    if limit <= 0:
        return []
    keep = list(messages[-limit:])
    while keep and not isinstance(keep[0], HumanMessage):
        keep.pop(0)
    return keep


class ContextNodes(NodeGroup):
    """Stateless context-prep nodes — constructed from ``AgentServices`` only."""

    def __init__(self, services) -> None:
        super().__init__(services)
        self._assembler = ContextAssembler()

    async def trim_history_node(self, state: GraphState) -> dict[str, Any]:
        """Trim chat history to the latest ``chat.max_messages`` turns.

        Runs *before* the parallel memory + knowledge branches so both consume the same
        trimmed window (knowledge's history-aware query rewrite must see exactly what
        memory sees).
        """
        messages: list[AnyMessage] = list(state.get("messages", []) or [])
        limit = self.prefs.history_window()
        keep = _trim_chat_history(messages, limit)
        if keep == messages:
            return {}
        log.info("trim_history - before=%d after=%d", len(messages), len(keep))
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *keep]}

    async def context_build_node(self, state: GraphState) -> dict[str, Any]:
        """Append the new user turn — and ONLY the user turn — to the (trimmed) history.

        Memory / knowledge / citation context is assembled ephemerally by ``compose_context`` into
        ``turn_context`` and injected by ``call_model`` into the current user turn; it must never
        enter ``messages`` (durable history stays clean across turns). See
        ``docs/context-assembly.md``.
        """
        text = state.get("user_text")
        if not text:
            # No usable input — leave messages untouched; call_model will short-circuit.
            return {}
        return {"messages": [HumanMessage(content=text)]}

    @graph_logged(captures={"decision"}, on_error="raise")
    async def compose_context_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        sources = state.get("knowledge_sources") or []
        # Instructions, Knowledge, and Memories are always present (sections render a
        # placeholder when empty); the citation instruction is conditional. Knowledge renders
        # from the structured sources (tagged, neutralized), not the pre-joined string.
        blocks = [
            block
            for block in (
                instructions_block(self.prefs.chat_instructions()),
                knowledge_block(sources),
                memory_block(
                    state.get("retrieved_memories") or [], self.prefs.memory_recall_render()
                ),
                citation_block(
                    has_sources=bool(sources),
                    cite_enabled=self.prefs.cite_sources(),
                ),
            )
            if block is not None
        ]
        turn_context = self._assembler.assemble(blocks=blocks)
        source_names = ",".join(block.source for block in blocks) or "none"
        observe(
            input=(
                f"knowledge: {len(sources)} · "
                f"memories: {len(state.get('retrieved_memories') or [])}"
            ),
            decision=("composed", source_names),
            output=f"blocks: {source_names} · chars={len(turn_context)}",
        )
        return {"turn_context": turn_context}
