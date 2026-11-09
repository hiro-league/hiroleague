"""An AI profile's limits (Phase 7a), read from the core's AI usage (Phase 7b: ``services/ai_usage``).

``max_cost_day`` (USD over the home's day; API models) and ``max_per_hour`` (asks in the current
clock hour; plan and local models). The home's day is the server machine's local day (the core has
no separate home time zone). The counts themselves live in ``ai_calls`` (``ai_usage.store``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ...domain.preferences import AiProfile
from ..ai_usage.store import ProfileUsage, hour_start

AskKind = str  # "api" | "local" | "plan"


def why_limited(
    profile: AiProfile, kind: AskKind, usage: ProfileUsage, now: datetime | None = None
) -> str | None:
    """Why the profile can't ask now, in words; None when it can."""
    now = now or datetime.now(UTC)
    if kind == "api" and profile.max_cost_day is not None and usage.cost_today >= profile.max_cost_day:
        return f"its ${profile.max_cost_day:g} for today is used (again after midnight)"
    if kind in ("plan", "local") and profile.max_per_hour is not None and usage.asks_this_hour >= profile.max_per_hour:
        again = (hour_start(now) + timedelta(hours=1)).astimezone()
        return f"its {profile.max_per_hour} asks this hour are used (again at {_clock(again)})"
    return None


def _clock(at: datetime) -> str:
    # 12-hour clock with AM/PM (people read this note).
    return at.strftime("%I:%M %p").lstrip("0")
