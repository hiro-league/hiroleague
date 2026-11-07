"""Always-on agent tools (Phase 5): offered to Hiro even when tools are off for the turn.

``chat.tools_enabled`` off (or the per-message opt-out) used to leave Hiro with no tools at
all; Hiro's own read-only abilities (reading what extensions know) stay on.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from hirocli.runtime.agent_graph.config import ChatGraphConfig
from hirocli.runtime.agent_graph.nodes.llm import LLMNodes
from hirocli.tools import all_tools
from hirocli.tools.registry import ToolRegistry


class BindingModel:
    """A chat model stand-in that remembers which tools each binding got."""

    def __init__(self, tools: tuple[str, ...] = ()) -> None:
        self.tools = tools

    def bind_tools(self, tools: Any, **kwargs: Any) -> "BindingModel":
        return BindingModel(tuple(t.name for t in tools))


def _nodes(always: frozenset[str]) -> LLMNodes:
    tools = [SimpleNamespace(name="extension_state"), SimpleNamespace(name="channel_disable")]
    config = ChatGraphConfig(model=BindingModel(), tools=tools, model_id="fake:m", system_prompt=None,
                             always_tool_names=always)
    services = SimpleNamespace(preferences=None, workspace_path=None)
    return LLMNodes(services=services, config=config)  # type: ignore[arg-type]


def test_tools_off_leaves_only_the_always_on_ones() -> None:
    nodes = _nodes(frozenset({"extension_state"}))
    assert nodes._bound.tools == ("extension_state", "channel_disable")
    assert nodes._bound_always.tools == ("extension_state",)


def test_tools_off_with_none_always_on_is_the_plain_model() -> None:
    nodes = _nodes(frozenset())
    assert nodes._bound_always is nodes._model


def test_reading_extensions_is_hiros_always_on_tool() -> None:
    registry = ToolRegistry()
    registry.register_all(all_tools())
    assert registry.agent_always_tool_names() == frozenset({"extension_state"})
    assert "extension_state" in {t.name for t in registry.agent_tools()}
