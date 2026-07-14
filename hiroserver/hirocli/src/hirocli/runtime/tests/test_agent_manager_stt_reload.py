"""Tests for AgentManager hot-reloading STT when ``llm.default_stt`` changes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from hirocli.runtime.agent_graph import ChatAgentGraph
from hirocli.runtime.agent_manager import AgentManager
from hirocli.runtime.tests.graph_fakes import make_agent_services
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


def _tts_double(tag: str):
    return SimpleNamespace(tag=tag, is_available=lambda: True)


def _memory_double(tag: str):
    return SimpleNamespace(tag=tag)


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
    mgr._tool_registry = None
    mgr._lc_agent_tools = None
    mgr._tts = _tts_double("initial-tts")
    mgr._stt = _stt_double("initial")
    mgr._memory = None
    mgr._vision = None
    mgr._credentials = None
    mgr._checkpointer = None
    mgr._compiled_cache = {}
    mgr._compiled_cache_max = 24
    mgr._providers_change_lock = asyncio.Lock()
    mgr._graph = ChatAgentGraph(
        make_agent_services(
            workspace_path,
            stt=mgr._stt,
            tts=mgr._tts,
            memory=mgr._memory,
            preferences=runtime,
        )
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
        assert mgr._graph.services.stt is new_stt
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_providers_changed_event_reloads_stt_tts_and_clears_compiled_cache(
    tmp_path: Path,
) -> None:
    """Domain ``PROVIDERS_CHANGED`` reloads STT and TTS bindings + cache bust."""
    secrets: dict[tuple[str, str], str] = {}
    mgr = _make_agent_manager(tmp_path)
    mgr._credentials = CredentialStore(tmp_path, "ws-test", _test_secrets=secrets)
    mgr._compiled_cache["dummy"] = object()
    new_stt = _stt_double("after-providers-stt")
    new_tts = _tts_double("after-providers-tts")
    new_memory = _memory_double("after-providers-memory")
    stt_rebuilds: list[Path] = []
    tts_rebuilds: list[Path] = []
    memory_rebuilds: list[Path] = []

    def fake_create_stt_service(workspace_path: Path, *, prefs=None):
        stt_rebuilds.append(workspace_path)
        return new_stt

    def fake_create_tts_service(workspace_path: Path, *, prefs=None):
        tts_rebuilds.append(workspace_path)
        return new_tts

    def fake_create_memory_service(workspace_path: Path, prefs, *, credential_store=None):
        memory_rebuilds.append(workspace_path)
        return new_memory

    with (
        patch(
            "hirocli.services.stt.create_stt_service",
            side_effect=fake_create_stt_service,
        ),
        patch(
            "hirocli.services.tts.create_tts_service",
            side_effect=fake_create_tts_service,
        ),
        patch(
            "hirocli.services.memory.create_memory_service",
            side_effect=fake_create_memory_service,
        ),
    ):
        bus = get_domain_event_bus()
        bus.subscribe(DomainEventType.PROVIDERS_CHANGED, mgr._handle_providers_changed)
        try:
            bus.publish(
                DomainEvent(
                    type=DomainEventType.PROVIDERS_CHANGED,
                    workspace_path=tmp_path,
                    payload={"reason": "test"},
                ),
            )
            await asyncio.sleep(0.08)
        finally:
            bus.unsubscribe(DomainEventType.PROVIDERS_CHANGED, mgr._handle_providers_changed)

    assert mgr._compiled_cache == {}
    assert stt_rebuilds == [tmp_path]
    assert tts_rebuilds == [tmp_path]
    assert memory_rebuilds == [tmp_path]
    assert mgr._stt is new_stt
    assert mgr._graph.services.stt is new_stt
    assert mgr._tts is new_tts
    assert mgr._graph.services.tts is new_tts
    assert mgr._memory is new_memory
    assert mgr._graph.services.memory is new_memory


@pytest.mark.asyncio
async def test_default_tts_change_swaps_tts_on_manager_and_graph(
    tmp_path: Path,
) -> None:
    mgr = _make_agent_manager(tmp_path)
    reactor: PreferenceReactor = mgr._ctx.preference_reactor

    new_tts = _tts_double("rebuilt-tts")
    rebuilds: list[Path] = []

    def fake_create_tts_service(workspace_path: Path, *, prefs=None):
        rebuilds.append(workspace_path)
        return new_tts

    try:
        reactor.on_change(
            "llm.default_tts",
            mgr._reload_tts_on_change,
            key="agent.tts",
            debounce_ms=10,
        )

        with patch(
            "hirocli.services.tts.create_tts_service",
            side_effect=fake_create_tts_service,
        ):
            mgr._ctx.preferences.update(
                "llm.default_tts", "openai:gpt-4o-mini-tts",
            )
            await asyncio.sleep(0.1)

        assert rebuilds == [tmp_path]
        assert mgr._tts is new_tts
        assert mgr._graph.services.tts is new_tts
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_memory_model_preferences_swap_memory_on_manager_and_graph(
    tmp_path: Path,
) -> None:
    mgr = _make_agent_manager(tmp_path)
    reactor: PreferenceReactor = mgr._ctx.preference_reactor

    new_memory = _memory_double("rebuilt-memory")
    rebuilds: list[tuple[Path, object | None]] = []

    def fake_create_memory_service(workspace_path: Path, prefs, *, credential_store=None):
        rebuilds.append((workspace_path, credential_store))
        return new_memory

    try:
        reactor.on_change(
            "memory",
            mgr._reload_memory_on_change,
            key="agent.memory",
            debounce_ms=10,
        )

        with patch(
            "hirocli.services.memory.create_memory_service",
            side_effect=fake_create_memory_service,
        ):
            # memory.enabled defaults to True — must flip for an effective change / reload.
            mgr._ctx.preferences.update_many({"memory.enabled": False})
            await asyncio.sleep(0.1)

        assert rebuilds == [(tmp_path, None)]
        assert mgr._memory is new_memory
        assert mgr._graph.services.memory is new_memory
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_graph_engine_change_reloads_memory(
    tmp_path: Path,
) -> None:
    # Memory rides the shared Graphiti engine, so a top-level ``graph.*`` change must rebuild
    # the memory service (mem0 → Graphiti, Phase 5) — the engine config is baked in at build.
    mgr = _make_agent_manager(tmp_path)
    reactor: PreferenceReactor = mgr._ctx.preference_reactor

    new_memory = _memory_double("rebuilt-memory-tuning")
    rebuilds: list[Path] = []

    def fake_create_memory_service(workspace_path: Path, prefs, *, credential_store=None):
        rebuilds.append(workspace_path)
        return new_memory

    try:
        reactor.on_change(
            "graph",
            mgr._reload_memory_on_change,
            key="agent.graph-memory",
            debounce_ms=10,
        )

        with patch(
            "hirocli.services.memory.create_memory_service",
            side_effect=fake_create_memory_service,
        ):
            mgr._ctx.preferences.update(
                "graph.search_recipe",
                "mmr",
            )
            await asyncio.sleep(0.1)

        assert rebuilds == [tmp_path]
        assert mgr._memory is new_memory
        assert mgr._graph.services.memory is new_memory
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_llm_tuning_profile_change_evicts_compiled_cache(
    tmp_path: Path,
) -> None:
    mgr = _make_agent_manager(tmp_path)
    reactor: PreferenceReactor = mgr._ctx.preference_reactor
    mgr._compiled_cache["cached"] = object()

    try:
        reactor.on_change(
            "llm.default_tuning_profile",
            mgr._evict_compiled_cache_on_llm_tuning_change,
            key="agent.chat-cache",
            debounce_ms=10,
        )

        mgr._ctx.preferences.update(
            "llm.default_tuning_profile",
            "memory_extraction",
        )
        await asyncio.sleep(0.1)

        assert mgr._compiled_cache == {}
    finally:
        reactor.close()


@pytest.mark.asyncio
async def test_providers_changed_event_ignored_for_other_workspace(
    tmp_path: Path,
) -> None:
    secrets: dict[tuple[str, str], str] = {}
    mgr = _make_agent_manager(tmp_path)
    mgr._credentials = CredentialStore(tmp_path, "ws-test", _test_secrets=secrets)
    mgr._compiled_cache["keep"] = object()
    initial_stt = mgr._stt
    initial_tts = mgr._tts
    initial_memory = mgr._memory

    with (
        patch(
            "hirocli.services.stt.create_stt_service",
            side_effect=lambda *a, **k: _stt_double("should-not-run"),
        ),
        patch(
            "hirocli.services.tts.create_tts_service",
            side_effect=lambda *a, **k: _tts_double("should-not-run"),
        ),
        patch(
            "hirocli.services.memory.create_memory_service",
            side_effect=lambda *a, **k: _memory_double("should-not-run"),
        ),
    ):
        bus = get_domain_event_bus()
        bus.subscribe(DomainEventType.PROVIDERS_CHANGED, mgr._handle_providers_changed)
        try:
            other = tmp_path / "other_ws"
            other.mkdir()
            bus.publish(
                DomainEvent(
                    type=DomainEventType.PROVIDERS_CHANGED,
                    workspace_path=other,
                    payload={},
                ),
            )
            await asyncio.sleep(0.06)
        finally:
            bus.unsubscribe(DomainEventType.PROVIDERS_CHANGED, mgr._handle_providers_changed)

    assert "keep" in mgr._compiled_cache
    assert mgr._stt is initial_stt
    assert mgr._tts is initial_tts
    assert mgr._memory is initial_memory


@pytest.mark.asyncio
async def test_unrelated_preference_change_does_not_reload_stt_or_tts(
    tmp_path: Path,
) -> None:
    mgr = _make_agent_manager(tmp_path)
    reactor: PreferenceReactor = mgr._ctx.preference_reactor
    initial_stt = mgr._stt
    initial_tts = mgr._tts
    initial_memory = mgr._memory

    stt_rebuilds: list[Path] = []
    tts_rebuilds: list[Path] = []
    memory_rebuilds: list[Path] = []

    def fake_create_stt_service(workspace_path: Path, *, prefs=None):
        stt_rebuilds.append(workspace_path)
        return _stt_double("rebuilt")

    def fake_create_tts_service(workspace_path: Path, *, prefs=None):
        tts_rebuilds.append(workspace_path)
        return _tts_double("rebuilt")

    def fake_create_memory_service(workspace_path: Path, prefs, *, credential_store=None):
        memory_rebuilds.append(workspace_path)
        return _memory_double("rebuilt")

    try:
        reactor.on_change(
            "llm.default_stt",
            mgr._reload_stt_on_change,
            key="agent.stt",
            debounce_ms=10,
        )
        reactor.on_change(
            "llm.default_tts",
            mgr._reload_tts_on_change,
            key="agent.tts",
            debounce_ms=10,
        )
        reactor.on_change(
            "memory",
            mgr._reload_memory_on_change,
            key="agent.memory",
            debounce_ms=10,
        )

        with (
            patch(
                "hirocli.services.stt.create_stt_service",
                side_effect=fake_create_stt_service,
            ),
            patch(
                "hirocli.services.tts.create_tts_service",
                side_effect=fake_create_tts_service,
            ),
            patch(
                "hirocli.services.memory.create_memory_service",
                side_effect=fake_create_memory_service,
            ),
        ):
            mgr._ctx.preferences.update("chat.max_messages", 9)
            await asyncio.sleep(0.05)

        assert stt_rebuilds == []
        assert tts_rebuilds == []
        assert memory_rebuilds == []
        assert mgr._stt is initial_stt
        assert mgr._tts is initial_tts
        assert mgr._memory is initial_memory
    finally:
        reactor.close()
