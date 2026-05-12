"""Tests for AgentManager hot-reloading STT when ``llm.default_stt`` changes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio

from hirocli.domain.events import get_domain_event_bus
from hirocli.runtime.agent_graph.base import BaseAgentGraph
from hirocli.runtime.agent_manager import AgentManager
from hirocli.runtime.preference_reactor import PreferenceReactor
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime


@pytest_asyncio.fixture(autouse=True)
async def _bus_attached_to_loop():
    bus = get_domain_event_bus()
    bus.reset()
    bus.attach_loop(asyncio.get_running_loop())
    yield
    bus.reset()


def _stt_double(tag: str):
    return SimpleNamespace(tag=tag, is_available=lambda: True)


def _make_agent_manager(workspace_path: Path) -> AgentManager:
    """Construct an AgentManager wired against a real reactor + preferences runtime.

    Skips ``AgentManager.__init__``: it needs a CommunicationManager / loop that
    aren't relevant to the reload path under test. We assemble just enough state
    by hand: workspace path, preferences runtime, reactor, and a graph holder.
    """
    runtime = WorkspacePreferencesRuntime(workspace_path)
    reactor = PreferenceReactor(workspace_path)
    ctx = SimpleNamespace(
        workspace_path=workspace_path,
        preferences=runtime,
        preference_reactor=reactor,
    )
    mgr = AgentManager.__new__(AgentManager)
    mgr._ctx = ctx
    mgr._comm = None
    mgr._tts = None
    mgr._stt = _stt_double("initial")
    mgr._vision = None
    mgr._credentials = None
    mgr._checkpointer = None
    mgr._compiled_cache = {}
    mgr._compiled_cache_max = 24
    mgr._graph = BaseAgentGraph(
        workspace_path=workspace_path,
        stt_service=mgr._stt,
        vision_service=None,
        tts_service=None,
        credential_store=None,
        checkpointer=None,
        preferences=runtime,
    )
    return mgr


@pytest.mark.asyncio
async def test_default_stt_change_swaps_stt_on_manager_and_graph(
    tmp_path: Path,
) -> None:
    mgr = _make_agent_manager(tmp_path)
    reactor: PreferenceReactor = mgr._ctx.preference_reactor

    new_stt = _stt_double("rebuilt")
    rebuilds: list[Path] = []

    def fake_create_stt_service(workspace_path: Path, *, prefs=None):
        rebuilds.append(workspace_path)
        return new_stt

    try:
        reactor.on_change(
            "llm.default_stt",
            mgr._reload_stt_on_change,
            key="agent.stt",
            debounce_ms=10,
        )

        with patch(
            "hirocli.services.stt.create_stt_service",
            side_effect=fake_create_stt_service,
        ):
            mgr._ctx.preferences.update(
                "llm.default_stt", "openai:gpt-4o-mini-transcribe",
            )
            await asyncio.sleep(0.1)

        assert rebuilds == [tmp_path]
        assert mgr._stt is new_stt
        assert mgr._graph._stt is new_stt
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_unrelated_preference_change_does_not_reload_stt(
    tmp_path: Path,
) -> None:
    mgr = _make_agent_manager(tmp_path)
    reactor: PreferenceReactor = mgr._ctx.preference_reactor
    initial_stt = mgr._stt

    rebuilds: list[Path] = []

    def fake_create_stt_service(workspace_path: Path, *, prefs=None):
        rebuilds.append(workspace_path)
        return _stt_double("rebuilt")

    try:
        reactor.on_change(
            "llm.default_stt",
            mgr._reload_stt_on_change,
            key="agent.stt",
            debounce_ms=10,
        )

        with patch(
            "hirocli.services.stt.create_stt_service",
            side_effect=fake_create_stt_service,
        ):
            mgr._ctx.preferences.update("memory.max_messages", 9)
            await asyncio.sleep(0.05)

        assert rebuilds == []
        assert mgr._stt is initial_stt
    finally:
        reactor.close()
