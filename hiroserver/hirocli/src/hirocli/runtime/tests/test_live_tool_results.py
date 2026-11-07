"""Live tools' results from earlier turns reach the model as out of date (Tool.agent_live).

The case behind it: "who is home" read at 4:29 PM stayed in the conversation, and at 6:44 PM
"when did Maro get home?" was answered from it ("away") without reading again.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from hirocli.runtime.agent_graph.nodes.call_model_support import retire_live_results, stale_note
from hirocli.tools import all_tools
from hirocli.tools.registry import ToolRegistry

LIVE = frozenset({"extension_state"})


def _read(call_id: str, result: str, *, named: bool = False) -> list:
    call = AIMessage(content="", tool_calls=[{"id": call_id, "name": "extension_state", "args": {}}])
    return [call, ToolMessage(content=result, tool_call_id=call_id, name="extension_state" if named else None)]


def test_an_earlier_turns_read_is_out_of_date_and_this_turns_stays() -> None:
    messages = [
        HumanMessage("Who is home"), *_read("c1", "Maro: away since 1:51 PM"), AIMessage("Only Michel."),
        HumanMessage("When did Maro get home?"), *_read("c2", "Maro: home since 5:26 PM"),
    ]
    out = retire_live_results(messages, LIVE)
    assert out[2].content == stale_note("extension_state")  # 4:29 PM read: out of date
    assert out[6].content == "Maro: home since 5:26 PM"  # read in this turn: as it is
    assert messages[2].content == "Maro: away since 1:51 PM"  # the stored history is untouched


def test_found_by_name_too_and_other_tools_keep_their_results() -> None:
    other = [AIMessage(content="", tool_calls=[{"id": "o1", "name": "device_list", "args": {}}]),
             ToolMessage(content="2 devices", tool_call_id="o1")]
    messages = [HumanMessage("hi"), *_read("x", "old", named=True), *other, AIMessage("ok"), HumanMessage("now?")]
    out = retire_live_results(messages, LIVE)
    assert out[2].content == stale_note("extension_state")
    assert out[4].content == "2 devices"


def test_nothing_changes_without_live_tools() -> None:
    messages = [HumanMessage("a"), *_read("c1", "r"), HumanMessage("b")]
    assert [m.content for m in retire_live_results(messages, frozenset())] == [m.content for m in messages]


def test_reading_extensions_is_a_live_tool() -> None:
    registry = ToolRegistry()
    registry.register_all(all_tools())
    assert registry.agent_live_tool_names() == LIVE
