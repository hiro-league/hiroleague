"""Declarative mapping from workspace-domain signals to logical resources."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceSpec:
    """Maps workspace-domain PubSub signals to a logical ``resource`` name."""

    name: str
    on_signals: frozenset[str]


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
        name="policy",
        on_signals=frozenset({"preferences_saved"}),
    ),
)


class ResourceRegistry:
    """Resolves which resources should invalidate when a domain signal fires."""

    def __init__(self, specs: tuple[ResourceSpec, ...] = DEFAULT_RESOURCE_REGISTRY) -> None:
        self._specs = specs

    def resources_for_signal(self, signal: str) -> list[str]:
        return [s.name for s in self._specs if signal in s.on_signals]
