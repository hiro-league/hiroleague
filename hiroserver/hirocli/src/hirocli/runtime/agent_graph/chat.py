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
from langgraph.types import RetryPolicy

from .config import ChatGraphConfig
from .nodes.conversation import ConversationNodes
from .nodes.media import MediaNodes
from .services import AgentServices
from .state import GraphState

_RETRY_TWICE = RetryPolicy(max_attempts=2)
RETRY_POLICIES: dict[str, RetryPolicy] = {
    "stt": _RETRY_TWICE,
    "vision": _RETRY_TWICE,
    "memory_search": _RETRY_TWICE,
    "memory_out": _RETRY_TWICE,
    "tts": _RETRY_TWICE,
}


def _retry_for(label: str) -> RetryPolicy | None:
    return RETRY_POLICIES.get(label)


class ChatAgentGraph:
    """Standalone chat graph builder — composes ``MediaNodes`` + ``ConversationNodes``."""

    def __init__(self, services: AgentServices) -> None:
        self.services = services

    def build(self, config: ChatGraphConfig) -> CompiledStateGraph:
        media = MediaNodes(self.services)
        conv = ConversationNodes(self.services, config)
        b = StateGraph(GraphState)

        for label, fn in media.registered_nodes().items():
            kwargs: dict = {}
            if (retry := _retry_for(label)) is not None:
                kwargs["retry_policy"] = retry
            b.add_node(label, fn, **kwargs)

        skip_conv: set[str] = set()
        if not config.tools:
            skip_conv.add("tools")
        if self.services.knowledge_subgraph is None:
            skip_conv.add("knowledge_retrieve")

        for label, fn in conv.registered_nodes().items():
            if label in skip_conv:
                continue
            kwargs = {}
            if (retry := _retry_for(label)) is not None:
                kwargs["retry_policy"] = retry
            b.add_node(label, fn, **kwargs)

        tools = bool(config.tools)
        knowledge_on = self.services.knowledge_subgraph is not None

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
