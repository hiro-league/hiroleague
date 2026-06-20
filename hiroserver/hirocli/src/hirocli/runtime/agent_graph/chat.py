"""ChatAgentGraph — thin builder composing media + conversation node groups.

The flow is:

    ingest → dispatch_media (Send fan-out) → stt | vision | (none)
           → gather → input_gate
                       ├── trim_history → {memory_search ∥ knowledge_retrieve?}
                       │      → context_build → compose_context → call_model
                       │      → tools (loop) → memory_out → tts? → finalize → END
                       └── media_failed → tts? → finalize → END

``trim_history`` runs once, then memory and (optionally) knowledge retrieval run in
parallel off the same trimmed window and join at ``context_build``. The knowledge branch
is added only when a retrieval subgraph is wired and the per-message toggle is on.

``input_gate`` short-circuits the LLM hop when ``gather`` produced no
``user_text`` (e.g. audio-only inbound where STT errored). Without this,
``call_model`` would be invoked against the prior message history with no
new turn appended and burn the full context for nothing — see
``media_failed_node`` for the canned-reply emission.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from .config import ChatGraphConfig
from .nodes.conversation import ConversationNodes
from .nodes.media import MediaNodes
from .services import AgentServices
from .state import GraphState

_RETRY_TWICE = RetryPolicy(max_attempts=2)


class ChatAgentGraph:
    """Standalone chat graph builder — composes ``MediaNodes`` + ``ConversationNodes``."""

    def __init__(self, services: AgentServices) -> None:
        self.services = services

    def build(self, config: ChatGraphConfig) -> CompiledStateGraph:
        media = MediaNodes(self.services)
        conv = ConversationNodes(self.services, config)
        b = StateGraph(GraphState)

        b.add_node("ingest", media.ingest_node)
        b.add_node("stt", media.stt_node, retry_policy=_RETRY_TWICE)
        b.add_node("vision", media.vision_node, retry_policy=_RETRY_TWICE)
        b.add_node("gather", media.gather_node)
        b.add_node("media_failed", media.media_failed_node)
        b.add_node("trim_history", conv.trim_history_node)
        b.add_node("memory_search", conv.memory_search_node, retry_policy=_RETRY_TWICE)
        b.add_node("context_build", conv.context_build_node)
        b.add_node("compose_context", conv.compose_context_node)
        b.add_node("call_model", conv.call_model_node)
        b.add_node("memory_out", conv.memory_out_node, retry_policy=_RETRY_TWICE)
        b.add_node("tts", conv.tts_node, retry_policy=_RETRY_TWICE)
        b.add_node("finalize", conv.finalize_node)

        tools = config.tools
        if tools:
            b.add_node("tools", conv.tools_node)

        knowledge_on = self.services.knowledge_subgraph is not None
        if knowledge_on:
            b.add_node("knowledge_retrieve", conv.knowledge_retrieve_node)

        b.add_edge(START, "ingest")
        b.add_conditional_edges("ingest", media.dispatch_media, ["stt", "vision", "gather"])
        b.add_edge("stt", "gather")
        b.add_edge("vision", "gather")
        b.add_conditional_edges("gather", media.input_gate, ["trim_history", "media_failed"])
        if knowledge_on:
            b.add_conditional_edges(
                "trim_history", conv.knowledge_fanout, ["memory_search", "knowledge_retrieve"]
            )
            b.add_edge("knowledge_retrieve", "context_build")
        else:
            b.add_edge("trim_history", "memory_search")
        b.add_edge("memory_search", "context_build")
        b.add_edge("context_build", "compose_context")
        b.add_edge("compose_context", "call_model")

        if tools:
            b.add_conditional_edges("call_model", conv.should_continue, ["tools", "memory_out"])
            b.add_edge("tools", "call_model")
        else:
            b.add_edge("call_model", "memory_out")

        b.add_conditional_edges("memory_out", conv.tts_gate, ["tts", "finalize"])
        b.add_conditional_edges("media_failed", conv.tts_gate, ["tts", "finalize"])
        b.add_edge("tts", "finalize")
        b.add_edge("finalize", END)

        return b.compile(checkpointer=self.services.checkpointer)

    def set_stt_service(self, stt_service) -> None:
        self.services.stt = stt_service

    def set_tts_service(self, tts_service) -> None:
        self.services.tts = tts_service

    def set_memory_service(self, memory_service) -> None:
        self.services.memory = memory_service

    def set_knowledge_subgraph(self, knowledge_subgraph: CompiledStateGraph | None) -> None:
        self.services.knowledge_subgraph = knowledge_subgraph
