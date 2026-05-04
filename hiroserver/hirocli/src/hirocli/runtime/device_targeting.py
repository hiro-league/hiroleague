"""Maps scopes / identities to gateway-connected devices."""

from __future__ import annotations

from typing import Any


class DeviceTargeting:
    """Returns recipients for outbound hint events.

    Tier 1: broadcast every hint to every currently-connected approved device.
    Later: filter by ``scope`` (e.g. ``user_id``).
    """

    def device_ids_for_connected(
        self,
        connected: set[str],
        *,
        _scope: dict[str, Any] | None = None,
    ) -> list[str]:
        """`_scope` reserved for multi-user fan-out; Tier 1 ignores it."""
        _ = _scope
        return sorted(connected)
