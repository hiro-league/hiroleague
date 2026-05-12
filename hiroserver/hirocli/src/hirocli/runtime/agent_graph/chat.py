"""ChatAgentGraph — wires reusable nodes into the chat agent flow.

The flow is:

    ingest → dispatch_media (Send fan-out) → stt | vision | (none)
           → gather → memory_in → context_build → call_model
           → tools (loop) → memory_out → tts? → END

Single graph variant for now (chat). Future variants (voice-only, transcribe-
only) would subclass ``BaseAgentGraph`` similarly.
"""

from __future__ import annotations

from functools import partial

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import RetryPolicy

from .base import BaseAgentGraph


_RETRY_TWICE = RetryPolicy(max_attempts=2)


class ChatAgentGraph(BaseAgentGraph):
    """Single chat agent flow (LLM + tools + STT + vision + optional TTS)."""

    def build(
        self,
        *,
        model: BaseChatModel,
        tools: list,
        system_prompt: str | None,
    ) -> CompiledStateGraph:
        b = self._new_state_graph()

        b.add_node("ingest", self.ingest_node)
        b.add_node("stt", self.stt_node, retry=_RETRY_TWICE)
        b.add_node("vision", self.vision_node, retry=_RETRY_TWICE)
        b.add_node("gather", self.gather_node)
        b.add_node("memory_in", self.memory_in_node)
        b.add_node("context_build", self.context_build_node)
        b.add_node(
            "call_model",
            self.make_call_model_node(model=model, tools=tools, system_prompt=system_prompt),
        )
        b.add_node("memory_out", self.memory_out_node)
        b.add_node("tts", self.tts_node, retry=_RETRY_TWICE)

        if tools:
            b.add_node("tools", ToolNode(tools))

        # Wiring
        b.add_edge(START, "ingest")
        # Fan-out: ingest decides which branches to spawn.
        b.add_conditional_edges("ingest", self.dispatch_media, ["stt", "vision", "gather"])
        b.add_edge("stt", "gather")
        b.add_edge("vision", "gather")
        b.add_edge("gather", "memory_in")
        b.add_edge("memory_in", "context_build")
        b.add_edge("context_build", "call_model")

        if tools:
            b.add_conditional_edges("call_model", self.should_continue, ["tools", "memory_out"])
            b.add_edge("tools", "call_model")
        else:
            b.add_edge("call_model", "memory_out")

        b.add_conditional_edges("memory_out", self.tts_gate, ["tts", END])
        b.add_edge("tts", END)

        return b.compile(checkpointer=self._checkpointer)
