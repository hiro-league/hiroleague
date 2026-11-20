"""UTC timestamp helpers shared across Hiro services."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


def utc_iso(value: datetime) -> str:
    """Format datetime as ISO 8601 UTC using trailing Z."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso8601_utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp and normalize to UTC."""
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt.astimezone(UTC)


def _clock_12h(value: datetime, seconds: bool = False) -> str:
    hour12 = value.hour % 12 or 12
    suffix = "AM" if value.hour < 12 else "PM"
    sec = f":{value.second:02d}" if seconds else ""
    return f"{hour12}:{value.minute:02d}{sec} {suffix}"


def human_datetime(value: datetime, now: datetime | None = None, *, seconds: bool = False) -> str:
    """Format a moment for people: "Today, 1:15 PM", "Yesterday, 11:57 PM", "Mon, Sep 28, 9:05 AM"
    (with `seconds`, "Today, 1:15:46 PM": a log line's time).

    12-hour clock, always with the day; the year only when it isn't this year. Spelled out by hand
    (not strftime's %p / locale) so a 24-hour system locale can't change it. Both datetimes are
    shown in the machine's local time zone.
    """
    local = value.astimezone()
    today = (now or datetime.now(UTC)).astimezone().date()
    clock = _clock_12h(local, seconds)
    days_ago = (today - local.date()).days
    if days_ago == 0:
        return f"Today, {clock}"
    if days_ago == 1:
        return f"Yesterday, {clock}"
    weekday = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[local.weekday()]
    month = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")[local.month - 1]
    year = f", {local.year}" if local.year != today.year else ""
    return f"{weekday}, {month} {local.day}{year}, {clock}"
