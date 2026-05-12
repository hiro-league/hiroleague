from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from hirocli.runtime.agent_graph.base import BaseAgentGraph
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime


@pytest.mark.asyncio
async def test_memory_in_node_uses_runtime_memory_max_messages(tmp_path) -> None:
    runtime = WorkspacePreferencesRuntime(tmp_path)
    runtime.update("memory.max_messages", 3)
    graph = BaseAgentGraph(
        workspace_path=tmp_path,
        stt_service=None,
        vision_service=None,
        tts_service=None,
        credential_store=None,
        checkpointer=None,
        preferences=runtime,
    )

    messages = [HumanMessage(content=f"m{i}") for i in range(5)]
    result = await graph.memory_in_node({"messages": messages})

    kept = result["messages"][1:]
    assert [msg.content for msg in kept] == ["m2", "m3", "m4"]
