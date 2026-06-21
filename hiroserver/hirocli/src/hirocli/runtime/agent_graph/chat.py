"""ChatAgentGraph — thin builder composing six cohesive node groups.

The flow is:

    ingest → dispatch_media (Send fan-out) → stt | vision | (none)
           → gather → input_gate
                       ├── trim_history → {memory_search ∥ knowledge_retrieve?}
                       │      → context_build → compose_context → call_model
                       │      → tools (loop) → memory_out → tts? → finalize → END
                       └── media_failed → tts? → finalize → END

Groups (review §1.5):

- ``MediaNodes`` — ingest, stt, vision, gather, media_failed (audio/image intake)
- ``ContextNodes`` — trim_history, context_build, compose_context
- ``MemoryNodes`` — memory_search, memory_out
- ``KnowledgeFanoutNodes`` — knowledge_retrieve + knowledge_fanout router
- ``LLMNodes`` — call_model, tools + should_continue router
- ``TTSNodes`` — tts, finalize + tts_gate router

``trim_history`` runs once, then memory and (optionally) knowledge retrieval run in
parallel off the same trimmed window and join at ``context_build``. The knowledge branch
is added only when a retrieval subgraph is wired (gated by ``KnowledgeFanoutNodes.is_active``).

``input_gate`` short-circuits the LLM hop when ``gather`` produced no ``user_text``
(e.g. audio-only inbound where STT errored). Without this, ``call_model`` would be
invoked against the prior message history with no new turn appended and burn the full
context for nothing — see ``media_failed_node`` for the canned-reply emission.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from .config import ChatGraphConfig
from .node_group import NodeGroup, mount as _mount
from .nodes.context import ContextNodes
from .nodes.knowledge import KnowledgeFanoutNodes
from .nodes.llm import LLMNodes
from .nodes.media import MediaNodes
from .nodes.memory import MemoryNodes
from .nodes.tts import TTSNodes
from .services import AgentServices
from .state import GraphState


def collected_retry_policies(*groups: NodeGroup) -> dict[str, RetryPolicy]:
    """Merged retry-policy view across groups — kept as a single map for test/debug use."""
    merged: dict[str, RetryPolicy] = {}
    for group in groups:
        for label, policy in group._RETRY_POLICIES.items():
            merged[label] = policy
    return merged


class ChatAgentGraph:
    """Chat graph builder — composes six cohesive node groups (see module docstring)."""

    def __init__(self, services: AgentServices) -> None:
        self.services = services

    def build(self, config: ChatGraphConfig) -> CompiledStateGraph:
        media = MediaNodes(self.services)
        context = ContextNodes(self.services)
        memory = MemoryNodes(self.services)
        knowledge = KnowledgeFanoutNodes(self.services)
        llm = LLMNodes(self.services, config)
        tts = TTSNodes(self.services)
        b = StateGraph(GraphState)

        for group in (media, context, memory, knowledge, llm, tts):
            _mount(b, group)

        # Feature gates come from the owning node group via ``is_active`` — single source
        # of truth for both registration (above, via ``registered_nodes``) and edge wiring.
        tools_on = llm.is_active("tools")
        knowledge_on = knowledge.is_active("knowledge_retrieve")

        b.add_edge(START, "ingest")
        b.add_conditional_edges("ingest", media.dispatch_media, ["stt", "vision", "gather"])
        b.add_edge("stt", "gather")
        b.add_edge("vision", "gather")
        b.add_conditional_edges("gather", media.input_gate, ["trim_history", "media_failed"])
        if knowledge_on:
            b.add_conditional_edges(
                "trim_history",
                knowledge.knowledge_fanout,
                ["memory_search", "knowledge_retrieve"],
            )
            b.add_edge("knowledge_retrieve", "context_build")
        else:
            b.add_edge("trim_history", "memory_search")
        b.add_edge("memory_search", "context_build")
        b.add_edge("context_build", "compose_context")
        b.add_edge("compose_context", "call_model")

        if tools_on:
            b.add_conditional_edges("call_model", llm.should_continue, ["tools", "memory_out"])
            b.add_edge("tools", "call_model")
        else:
            b.add_edge("call_model", "memory_out")

        b.add_conditional_edges("memory_out", tts.tts_gate, ["tts", "finalize"])
        b.add_conditional_edges("media_failed", tts.tts_gate, ["tts", "finalize"])
        b.add_edge("tts", "finalize")
        b.add_edge("finalize", END)

        return b.compile(checkpointer=self.services.checkpointer)
