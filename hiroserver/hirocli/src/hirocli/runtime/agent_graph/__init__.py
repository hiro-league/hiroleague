"""Agent graph package — reusable nodes + flow-specific graphs.

Public surface:
  - ``BaseAgentGraph`` — node methods + service injection + ``build()`` hook
  - ``ChatAgentGraph`` — the chat flow used today (only variant for now)
  - ``GraphState`` — TypedDict shared across all graphs
  - event constants (``GRAPH_*``) + ``make_event`` for emitting from nodes
"""

from __future__ import annotations

from .base import BaseAgentGraph, TRIMMED_MESSAGE_LIMIT, _normalize_reply_content
from .chat import ChatAgentGraph
from .events import (
    GRAPH_ERROR,
    GRAPH_INGEST_COMPLETED,
    GRAPH_REPLY_COMPLETED,
    GRAPH_STT_COMPLETED,
    GRAPH_TTS_COMPLETED,
    GRAPH_VISION_COMPLETED,
    make_event,
)
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
    "BaseAgentGraph",
    "ChatAgentGraph",
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
    "GRAPH_REPLY_COMPLETED",
    "GRAPH_TTS_COMPLETED",
    "GRAPH_ERROR",
    "make_event",
    "_normalize_reply_content",
]
