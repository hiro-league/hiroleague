"""Unit tests for ResourceRegistry signal → resource mapping."""

from __future__ import annotations

from hirocli.runtime.resource_registry import ResourceRegistry, ResourceSpec


def test_preferences_saved_maps_to_channels_policy_and_the_apps_profiles() -> None:
    reg = ResourceRegistry()
    names = reg.resources_for_signal("preferences_saved")
    assert set(names) == {"channels", "policy", "ai.profiles", "voice.profiles"}


def test_the_apps_copies_are_read_by_the_apps_the_rest_by_the_phones() -> None:
    """Unified communication, phase 4: one list of resources, each with who reads it."""
    reg = ResourceRegistry()
    assert reg.resources_for_signal("people_changed") == ["people"]
    assert reg.resources_for_signal("providers_changed") == ["ai.profiles"]
    assert {r: reg.read_by(r) for r in ("people", "ai.profiles", "voice.profiles", "channels", "policy")} == {
        "people": "apps", "ai.profiles": "apps", "voice.profiles": "apps", "channels": "devices", "policy": "devices"}


def test_character_changed_maps_to_channels_and_characters() -> None:
    reg = ResourceRegistry()
    names = reg.resources_for_signal("character_changed")
    assert set(names) == {"channels", "characters"}


def test_character_photo_changed_maps_to_characters_only() -> None:
    reg = ResourceRegistry()
    names = reg.resources_for_signal("character_photo_changed")
    assert names == ["characters"]


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
