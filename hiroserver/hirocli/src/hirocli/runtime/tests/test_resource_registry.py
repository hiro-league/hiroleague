"""Unit tests for ResourceRegistry signal → resource mapping."""

from __future__ import annotations

from hirocli.runtime.resource_registry import ResourceRegistry, ResourceSpec


def test_preferences_saved_maps_to_channels_and_policy() -> None:
    reg = ResourceRegistry()
    names = reg.resources_for_signal("preferences_saved")
    assert set(names) == {"channels", "policy"}


def test_character_changed_maps_to_channels_only() -> None:
    reg = ResourceRegistry()
    names = reg.resources_for_signal("character_changed")
    assert names == ["channels"]


def test_channel_changed_maps_to_channels_only() -> None:
    reg = ResourceRegistry()
    names = reg.resources_for_signal("channel_changed")
    assert names == ["channels"]


def test_unknown_signal_returns_empty() -> None:
    reg = ResourceRegistry()
    assert reg.resources_for_signal("bogus") == []


def test_custom_registry() -> None:
    reg = ResourceRegistry(
        (
            ResourceSpec(name="widgets", on_signals=frozenset({"widget_saved"})),
        ),
    )
    assert reg.resources_for_signal("widget_saved") == ["widgets"]
