"""Colored Quasar badges for enabled/disabled-style status.

Guidelines §4 table shows `status_badge(status: str)`; this API uses an explicit
bool until feature pages define a shared string→color map (Phase 2+).
"""

from __future__ import annotations

from nicegui import ui


def status_badge(label: str, *, positive: bool | None = None) -> None:
    """Render a QBadge-style chip: positive=True green, False grey, None neutral."""
    if positive is True:
        color = "positive"
    elif positive is False:
        color = "grey-6"
    else:
        color = "primary"
    ui.badge(label).props(f"color={color}")
