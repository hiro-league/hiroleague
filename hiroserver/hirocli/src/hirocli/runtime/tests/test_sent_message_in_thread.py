"""Phase 4: a message the core sent to the owner joins Hiro's own thread.

AgentManager.add_sent_message writes it with ``aupdate_state(as_node="finalize")``.
On the real chat graph that must leave the thread finished (nothing pending), keep
the message in the history, and let the next turn run from the top as usual.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hiro_commons.log import Logger
from langchain_core.messages import AIMessage

from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.runtime.tests.graph_fakes import make_inbound_envelope, run_graph
from hirocli.runtime.tests.state_contract_helpers import build_checkpointed_chat, turn_state


@pytest.fixture(autouse=True)
def _quiet_logger() -> None:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


@pytest.mark.asyncio
async def test_sent_message_joins_the_thread_between_turns(tmp_path: Path) -> None:
    compiled, _ = build_checkpointed_chat(tmp_path)
    config = {"configurable": {"thread_id": "t1"}}
    await run_graph(compiled, turn_state(tmp_path, make_inbound_envelope(text="hi")), config=config)

    await compiled.aupdate_state(config, {"messages": [AIMessage(content="Joe is home")]}, as_node="finalize")
    after_update = await compiled.aget_state(config)
    assert after_update.next == ()  # the thread is left finished, nothing pending

    await run_graph(
        compiled,
        turn_state(tmp_path, make_inbound_envelope(text="who's with him?"), inbound_id="in-2"),
        config=config,
    )
    final = await compiled.aget_state(config)
    assert final.next == ()  # the second turn ran to the end as usual
    texts = [(type(m).__name__, m.content) for m in final.values["messages"]]
    joe = texts.index(("AIMessage", "Joe is home"))
    follow_up = texts.index(("HumanMessage", "who's with him?"))
    assert joe < follow_up  # Hiro had the alert in its history when the owner replied
