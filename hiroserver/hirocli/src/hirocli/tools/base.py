"""Base Tool abstraction for Hiro.

A Tool is the single unit of functionality — it owns its schema and execution
logic.  Both CLI commands and the AI agent are thin callers that invoke
tool.execute() and render/forward the result.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolParam:
    """Descriptor for a single tool parameter."""

    type_: type
    description: str
    required: bool = True


class Tool(ABC):
    """Base class for all Hiro tools.

    Subclasses declare:
      - name:        unique snake_case identifier used by the agent and CLI
      - description: human/LLM-readable summary
      - params:      flat dict of ToolParam — single source of truth for
                     both CLI argument specs and LLM tool schemas
      - execute():   the actual logic, returns a plain dataclass result
      - runtime:     class attribute; True when the tool needs a live
                     ``CommunicationManager`` (see ToolRegistry RuntimeContext).

    Workspace-scoped tools use ``runtime = False`` (default). Tools that expose
    ``execute_async()`` are invoked via ``ToolRegistry.invoke_async`` from the
    server HTTP handler so the asyncio event loop is not deadlocked.
    """

    name: str
    description: str
    params: dict[str, ToolParam]
    # Class-level marker — instance lookup via ``type(self).runtime``
    runtime: bool = False

    def attach_runtime(self, ctx: Any) -> None:
        """Inject registry runtime context — no-op unless a subclass overrides."""

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any: ...
