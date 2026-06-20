"""Unit tests for ``ChatGraphConfig`` — the typed build-time config (P2)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from hirocli.runtime.agent_graph.config import ChatGraphConfig
from hirocli.runtime.tests.graph_fakes import ScriptedChatModel


def test_construction_with_all_fields() -> None:
    model = ScriptedChatModel(responses=[])
    config = ChatGraphConfig(
        model=model,
        tools=[object()],
        model_id="fake:model",
        system_prompt="You are Hiro.",
        temperature=0.5,
        max_tokens=128,
        thinking={"mode": "extended"},
    )
    assert config.model is model
    assert len(config.tools) == 1
    assert config.model_id == "fake:model"
    assert config.system_prompt == "You are Hiro."
    assert config.temperature == 0.5
    assert config.max_tokens == 128
    assert config.thinking == {"mode": "extended"}


def test_construction_defaults_optional_fields_to_none() -> None:
    model = ScriptedChatModel(responses=[])
    config = ChatGraphConfig(
        model=model,
        tools=[],
        model_id="fake:model",
        system_prompt=None,
    )
    assert config.temperature is None
    assert config.max_tokens is None
    assert config.thinking is None


def test_frozen_rejects_field_assignment() -> None:
    config = ChatGraphConfig(
        model=ScriptedChatModel(responses=[]),
        tools=[],
        model_id="fake:model",
        system_prompt=None,
    )
    with pytest.raises(FrozenInstanceError):
        config.model_id = "other"  # type: ignore[misc]


def test_equality_by_value() -> None:
    model = ScriptedChatModel(responses=[])
    left = ChatGraphConfig(
        model=model,
        tools=[],
        model_id="fake:model",
        system_prompt="Hi",
        temperature=0.1,
    )
    right = ChatGraphConfig(
        model=model,
        tools=[],
        model_id="fake:model",
        system_prompt="Hi",
        temperature=0.1,
    )
    assert left == right
