"""What each AI profile asked, per clock hour — workspace.db ``ai_usage`` (Phase 7a).

Enough for a profile's limits: ``max_cost_day`` (USD over the home's day; API models) and
``max_per_hour`` (asks in the current clock hour; plan and local models). The home's day is the
server machine's local day (the core has no separate home time zone). Rows older than
AI_USAGE_KEEP_DAYS are dropped when a new ask is counted.

Synchronous (sqlite3); the runner calls these in a worker thread.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ...domain.db import db_path, ensure_db
from ...domain.preferences import AiProfile

AI_USAGE_KEEP_DAYS = 40

AskKind = str  # "api" | "local" | "plan"


@dataclass(frozen=True)
class ProfileUsage:
    asks_today: int
    cost_today: float
    asks_this_hour: int


def hour_start(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def local_day_start(now: datetime) -> datetime:
    """Midnight of the server's local day containing ``now``, as a UTC moment."""
    return now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _key(at: datetime) -> str:
    return hour_start(at).strftime("%Y-%m-%dT%H:00:00Z")


def profile_usage(workspace_path: Path, profile_id: str, now: datetime | None = None) -> ProfileUsage:
    now = now or datetime.now(UTC)
    ensure_db(workspace_path)
    day_key = _key(local_day_start(now))
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        today = conn.execute(
            "SELECT COALESCE(SUM(asks), 0), COALESCE(SUM(cost), 0.0) FROM ai_usage WHERE profile_id = ? AND hour >= ?",
            (profile_id, day_key),
        ).fetchone()
        hour = conn.execute(
            "SELECT COALESCE(SUM(asks), 0) FROM ai_usage WHERE profile_id = ? AND hour = ?",
            (profile_id, _key(now)),
        ).fetchone()
    return ProfileUsage(asks_today=int(today[0]), cost_today=float(today[1]), asks_this_hour=int(hour[0]))


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


def record_ask(workspace_path: Path, profile_id: str, cost: float | None, now: datetime | None = None) -> None:
    """Count one answered ask (and its cost) in the profile's hour; drop hours past the keep window."""
    now = now or datetime.now(UTC)
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            "INSERT INTO ai_usage (profile_id, hour, asks, cost) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(profile_id, hour) DO UPDATE SET asks = asks + 1, cost = cost + excluded.cost",
            (profile_id, _key(now), float(cost or 0.0)),
        )
        conn.execute("DELETE FROM ai_usage WHERE hour < ?", (_key(now - timedelta(days=AI_USAGE_KEEP_DAYS)),))
        conn.commit()
