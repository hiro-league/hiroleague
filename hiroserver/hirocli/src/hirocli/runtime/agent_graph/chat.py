"""ChatAgentGraph — wires reusable nodes into the chat agent flow.

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
``media_failed_node`` in ``BaseAgentGraph`` for the canned-reply emission.

Single graph variant for now (chat). Future variants (voice-only, transcribe-
only) would subclass ``BaseAgentGraph`` similarly.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph
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
        model_id: str,
        system_prompt: str | None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thinking: Any = None,
    ) -> CompiledStateGraph:
        b = self._new_state_graph()

        b.add_node("ingest", self.ingest_node)
        b.add_node("stt", self.stt_node, retry=_RETRY_TWICE)
        b.add_node("vision", self.vision_node, retry=_RETRY_TWICE)
        b.add_node("gather", self.gather_node)
        b.add_node("media_failed", self.media_failed_node)
        b.add_node("trim_history", self.trim_history_node)
        b.add_node("memory_search", self.memory_search_node, retry=_RETRY_TWICE)
        b.add_node("context_build", self.context_build_node)
        b.add_node("compose_context", self.make_compose_context_node())
        b.add_node(
            "call_model",
            self.make_call_model_node(
                model=model,
                tools=tools,
                model_id=model_id,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking=thinking,
            ),
        )
        b.add_node("memory_out", self.memory_out_node, retry=_RETRY_TWICE)
        b.add_node("tts", self.tts_node, retry=_RETRY_TWICE)
        b.add_node("finalize", self.finalize_node)

        if tools:
            b.add_node("tools", self.make_tools_node(tools))

        knowledge_on = self._knowledge_subgraph is not None
        if knowledge_on:
            b.add_node("knowledge_retrieve", self.knowledge_retrieve_node)

        # Wiring
        b.add_edge(START, "ingest")
        # Fan-out: ingest decides which branches to spawn.
        b.add_conditional_edges("ingest", self.dispatch_media, ["stt", "vision", "gather"])
        b.add_edge("stt", "gather")
        b.add_edge("vision", "gather")
        # Skip the LLM entirely when this turn produced no usable user_text
        # (audio-only inbound + STT failure being the typical case).
        b.add_conditional_edges("gather", self.input_gate, ["trim_history", "media_failed"])
        # Trim once, up front, then run memory + knowledge in parallel off the same window.
        if knowledge_on:
            b.add_conditional_edges(
                "trim_history", self.knowledge_fanout, ["memory_search", "knowledge_retrieve"]
            )
            b.add_edge("knowledge_retrieve", "context_build")
        else:
            b.add_edge("trim_history", "memory_search")
        b.add_edge("memory_search", "context_build")
        # Assemble the ephemeral system message (persona + memory + knowledge) once, before the
        # tools loop; call_model reads it each iteration. Keeps memory/knowledge out of messages.
        b.add_edge("context_build", "compose_context")
        b.add_edge("compose_context", "call_model")

        if tools:
            b.add_conditional_edges("call_model", self.should_continue, ["tools", "memory_out"])
            b.add_edge("tools", "call_model")
        else:
            b.add_edge("call_model", "memory_out")

        b.add_conditional_edges("memory_out", self.tts_gate, ["tts", "finalize"])
        b.add_conditional_edges("media_failed", self.tts_gate, ["tts", "finalize"])
        b.add_edge("tts", "finalize")
        b.add_edge("finalize", END)

        return b.compile(checkpointer=self._checkpointer)
