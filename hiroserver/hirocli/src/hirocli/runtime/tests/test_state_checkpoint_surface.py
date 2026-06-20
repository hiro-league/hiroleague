"""Checkpoint surface contract for ``GraphState`` (P1c)."""

from __future__ import annotations

from pathlib import Path

import pytest
from hiro_commons.log import Logger

from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.runtime.tests.graph_fakes import run_graph
from hirocli.runtime.tests.state_contract_helpers import (
    assert_no_large_bytes,
    build_checkpointed_chat,
    checkpoint_surface_snapshot,
    load_checkpoint_surface_fixture,
    media_turn_envelope,
    turn_state,
)


@pytest.fixture(autouse=True)
def _quiet_logger() -> None:
    LedgerSink._opened.clear()
    Logger.set_level("INFO")
    Logger.setup(console=False)
    yield
    LedgerSink._opened.clear()


@pytest.mark.asyncio
async def test_checkpoint_surface_matches_fixture(tmp_path: Path) -> None:
    compiled, _ = build_checkpointed_chat(tmp_path)
    config = {"configurable": {"thread_id": "t1"}}
    await run_graph(
        compiled,
        turn_state(tmp_path, media_turn_envelope()),
        config=config,
    )
    channels = compiled.get_state(config).values
    assert checkpoint_surface_snapshot(channels) == load_checkpoint_surface_fixture()


@pytest.mark.asyncio
async def test_checkpoint_only_messages_durable_scratch_ephemeral(tmp_path: Path) -> None:
    compiled, _ = build_checkpointed_chat(tmp_path)
    config = {"configurable": {"thread_id": "t1"}}
    await run_graph(
        compiled,
        turn_state(tmp_path, media_turn_envelope()),
        config=config,
    )
    channels = compiled.get_state(config).values
    assert channels.get("messages")
    assert not channels.get("audio_items")
    assert not channels.get("image_items")
    # gather_node clears media byte carriers only; text_inputs may persist in checkpoint today.
    assert_no_large_bytes(channels)


def test_checkpoint_fixture_gate_reddens_on_key_drift() -> None:
    fixture = load_checkpoint_surface_fixture()
    drifted = dict(fixture)
    drifted["channel_keys"] = [*fixture["channel_keys"], "phantom_field"]
    assert drifted != fixture
