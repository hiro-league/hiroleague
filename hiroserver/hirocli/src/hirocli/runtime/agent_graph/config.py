"""Build-time configuration objects for the agent graphs.

Replaces the old kwargs-soup ``build()`` signature with a typed, immutable config.
Future stages extend this module (e.g. the P4 ``AgentServices`` DI container).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel


@dataclass(frozen=True)
class ChatGraphConfig:
    """Everything ``ChatAgentGraph.build`` needs to wire + bind one chat flow.

    Fields mirror the prior ``build()`` kwargs 1:1 (no behavior change). ``model`` is the
    already-constructed chat model; ``tools`` may be empty (the tools node is then omitted).
    """
    model: BaseChatModel
    tools: list
    model_id: str
    system_prompt: str | None
    temperature: float | None = None
    max_tokens: int | None = None
    thinking: Any = None
