"""Convert Hiro Tool objects into LangChain StructuredTool instances.

Kept as a separate module so importing tools/base.py and tools/device.py
never pulls in LangChain as a hard import-time dependency.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import Tool


def to_langchain(tool: Tool) -> Any:
    """Convert a single Hiro Tool into a LangChain StructuredTool."""
    from langchain_core.tools import StructuredTool
    from pydantic import Field, create_model

    fields: dict[str, Any] = {}
    for param_name, param in tool.params.items():
        if param.required:
            fields[param_name] = (param.type_, Field(description=param.description))
        else:
            fields[param_name] = (
                Optional[param.type_],
                Field(default=None, description=param.description),
            )

    args_model = create_model(f"{tool.name}_args", **fields)

    _tool = tool
    exec_async = getattr(tool, "execute_async", None)

    if callable(exec_async):
        async def _arun(**kwargs: Any) -> Any:
            return await exec_async(**kwargs)

        return StructuredTool.from_function(
            coroutine=_arun,
            name=tool.name,
            description=tool.description,
            args_schema=args_model,
        )

    def _run(**kwargs: Any) -> Any:
        return _tool.execute(**kwargs)

    return StructuredTool.from_function(
        func=_run,
        name=tool.name,
        description=tool.description,
        args_schema=args_model,
    )


def to_langchain_list(tools: list[Tool]) -> list[Any]:
    """Convert a list of Hiro Tools to LangChain tools."""
    return [to_langchain(t) for t in tools]
