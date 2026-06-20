"""Agent graph package — node groups + flow-specific graph builders.

Public surface:
  - ``AgentServices`` — mutable DI container for graph services
  - ``ChatAgentGraph`` — the chat flow builder used today
  - ``GraphState`` — TypedDict shared across all graphs
  - event constants (``GRAPH_*``) + ``make_event`` for emitting from nodes
"""

from __future__ import annotations

from .chat import ChatAgentGraph
from .config import ChatGraphConfig
from .events import (
    GRAPH_ERROR,
    GRAPH_INGEST_COMPLETED,
    GRAPH_LLM_USAGE,
    GRAPH_MEMORY_RETRIEVED,
    GRAPH_MEMORY_STORED,
    GRAPH_REPLY_COMPLETED,
    GRAPH_RUN_COMPLETED,
    GRAPH_RUN_FAILED,
    GRAPH_STT_COMPLETED,
    GRAPH_TOOL_COMPLETED,
    GRAPH_TTS_COMPLETED,
    GRAPH_VISION_COMPLETED,
    make_event,
)
from .graph_kit import normalize_reply_content
from .node_group import TRIMMED_MESSAGE_LIMIT
from .services import AgentServices
from .state import (
    AudioItem,
    GraphState,
    ImageItem,
    NodeError,
    ReplyAudio,
    Transcript,
    Vision,
)

__all__ = [
    "AgentServices",
    "ChatAgentGraph",
    "ChatGraphConfig",
    "GraphState",
    "TRIMMED_MESSAGE_LIMIT",
    "AudioItem",
    "ImageItem",
    "Transcript",
    "Vision",
    "NodeError",
    "ReplyAudio",
    "GRAPH_INGEST_COMPLETED",
    "GRAPH_STT_COMPLETED",
    "GRAPH_VISION_COMPLETED",
    "GRAPH_LLM_USAGE",
    "GRAPH_TOOL_COMPLETED",
    "GRAPH_MEMORY_RETRIEVED",
    "GRAPH_MEMORY_STORED",
    "GRAPH_REPLY_COMPLETED",
    "GRAPH_TTS_COMPLETED",
    "GRAPH_RUN_COMPLETED",
    "GRAPH_RUN_FAILED",
    "GRAPH_ERROR",
    "make_event",
    "normalize_reply_content",
]
