"""The one list of resources the core says "read it again" about (``resource.changed``), for the phones and the apps.

Each resource names the core changes (domain signals) that make it stale and who reads it: the phones (the device
app's lists) or the apps (their copies of the family and the AI and voice profiles, which the backend kit follows).
One sender (resource_change_broadcaster.py) sends each note to its readers, in one shape.
"""

from __future__ import annotations

from dataclasses import dataclass

from hiro_channel_sdk.constants import RESOURCE_AI_PROFILES, RESOURCE_PEOPLE, RESOURCE_VOICE_PROFILES

READ_BY_DEVICES = "devices"  # the phones (the device app)
READ_BY_APPS = "apps"  # the connected apps (extensions of kind app)


@dataclass(frozen=True)
class ResourceSpec:
    """A logical ``resource``, the domain signals that make it stale, and who reads it."""

    name: str
    on_signals: frozenset[str]
    read_by: str = READ_BY_DEVICES


# Signals mirror ResourceChangeBroadcaster / domain pub-sub identifiers (`preferences_saved`, …).
DEFAULT_RESOURCE_REGISTRY: tuple[ResourceSpec, ...] = (
    ResourceSpec(
        name="channels",
        on_signals=frozenset({
            "preferences_saved",
            "character_changed",
            "channel_changed",
        }),
    ),
    ResourceSpec(
        name="characters",
        on_signals=frozenset({
            "character_changed",
            "character_photo_changed",
        }),
    ),
    ResourceSpec(
        name="policy",
        on_signals=frozenset({"preferences_saved"}),
    ),
    # What the apps keep a copy of (unified communication, phase 4).
    ResourceSpec(name=RESOURCE_PEOPLE, on_signals=frozenset({"people_changed"}), read_by=READ_BY_APPS),
    # The profiles and the uses' picks live in the preferences; the AI profiles' rows also say which providers are set.
    ResourceSpec(
        name=RESOURCE_AI_PROFILES,
        on_signals=frozenset({"preferences_saved", "providers_changed"}),
        read_by=READ_BY_APPS,
    ),
    ResourceSpec(name=RESOURCE_VOICE_PROFILES, on_signals=frozenset({"preferences_saved"}), read_by=READ_BY_APPS),
)


class ResourceRegistry:
    """Resolves which resources should invalidate when a domain signal fires, and who reads each."""

    def __init__(self, specs: tuple[ResourceSpec, ...] = DEFAULT_RESOURCE_REGISTRY) -> None:
        self._specs = specs

    def resources_for_signal(self, signal: str) -> list[str]:
        return [s.name for s in self._specs if signal in s.on_signals]

    def read_by(self, resource: str) -> str:
        return next((s.read_by for s in self._specs if s.name == resource), READ_BY_DEVICES)
