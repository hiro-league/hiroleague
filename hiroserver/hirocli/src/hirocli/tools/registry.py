"""ToolRegistry — central dispatch for all Hiro tools.

The registry holds one instance of every registered Tool. Callers — HTTP POST
`/invoke`, tests — should use ``invoke_async`` from asyncio contexts so tools
that need the live inbound pipeline (e.g. ``message_send``) can ``await``.
Synchronous ``invoke()`` remains for offline callers but refuses async-only tools.

CLI commands and offline code that target workspace-scoped tools keep calling
``tool.execute()`` on imported instances directly when appropriate.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .base import Tool

if TYPE_CHECKING:
    from ..runtime.communication_manager import CommunicationManager


@dataclass(frozen=True)
class RuntimeContext:
    """Live handles for tools that need an in-process ``CommunicationManager``."""

    comm_manager: CommunicationManager

    #: Server event loop — same loop that runs FastAPI and CommunicationManager helpers.
    loop: asyncio.AbstractEventLoop


class ToolNotFoundError(Exception):
    """Raised when invoke() is called with an unknown tool name."""


class ToolAsyncOnlyError(Exception):
    """Tool must be awaited via invoke_async(); sync invoke() is unsupported."""


class ToolExecutionError(Exception):
    """Wraps an unexpected exception raised inside tool.execute()."""

    def __init__(self, tool_name: str, cause: Exception) -> None:
        super().__init__(f"Tool '{tool_name}' raised: {cause}")
        self.tool_name = tool_name
        self.cause = cause


@dataclass
class InvokeResult:
    """Structured return value from registry invoke methods."""

    tool_name: str
    result: Any


class ToolRegistry:
    """Holds tool instances and dispatches invoke() / invoke_async() calls."""

    def __init__(
        self,
        policy: PolicyFn | None = None,
        runtime: RuntimeContext | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._policy = policy
        self._runtime = runtime

    def register(self, tool: Tool) -> None:
        """Add a tool instance and attach runtime context when applicable."""
        self._tools[tool.name] = tool
        if self._runtime is not None and type(tool).runtime:
            tool.attach_runtime(self._runtime)

    def register_all(self, tools: list[Tool]) -> None:
        """Add multiple tool instances to the registry."""
        for tool in tools:
            self.register(tool)

    def names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def schema(self) -> list[dict[str, Any]]:
        """Return a JSON-serialisable schema for all registered tools."""
        result = []
        for tool in self._tools.values():
            result.append({
                "name": tool.name,
                "description": tool.description,
                "params": {
                    name: {
                        "type": param.type_.__name__,
                        "description": param.description,
                        "required": param.required,
                    }
                    for name, param in tool.params.items()
                },
            })
        return result

    def invoke(self, tool_name: str, params: dict[str, Any] | None = None) -> InvokeResult:
        """Synchronous dispatch. Async-only tools raise ``ToolAsyncOnlyError``."""
        if tool_name not in self._tools:
            raise ToolNotFoundError(f"Unknown tool: '{tool_name}'. Available: {self.names()}")

        if self._policy is not None:
            self._policy(tool_name, params or {})

        tool = self._tools[tool_name]
        safe_params = {k: v for k, v in (params or {}).items() if k in tool.params}

        if callable(getattr(tool, "execute_async", None)):
            raise ToolAsyncOnlyError(
                f"Tool '{tool_name}' is async-only — use invoke_async()."
            )

        try:
            result = tool.execute(**safe_params)
        except Exception as exc:
            raise ToolExecutionError(tool_name, exc) from exc

        return InvokeResult(tool_name=tool_name, result=result)

    async def invoke_async(self, tool_name: str, params: dict[str, Any] | None = None) -> InvokeResult:
        """Async dispatch — ``execute_async()`` when defined, else executor-backed ``execute()``."""
        if tool_name not in self._tools:
            raise ToolNotFoundError(f"Unknown tool: '{tool_name}'. Available: {self.names()}")

        if self._policy is not None:
            self._policy(tool_name, params or {})

        tool = self._tools[tool_name]
        safe_params = {k: v for k, v in (params or {}).items() if k in tool.params}

        exec_async = getattr(tool, "execute_async", None)
        try:
            if callable(exec_async):
                result = await exec_async(**safe_params)
            else:
                result = await asyncio.to_thread(tool.execute, **safe_params)
        except Exception as exc:
            raise ToolExecutionError(tool_name, exc) from exc

        return InvokeResult(tool_name=tool_name, result=result)


# Type alias for the optional policy callable.
PolicyFn = "Callable[[str, dict[str, Any]], None]"
