"""Times written into words the UI shows (a reason, a note): the house format, as the frontend's
lib/format/time.ts. 12-hour with AM/PM, never 24-hour, and always which day (CLAUDE.md, "Dates and
times"). The backend writes them into sentences, so they read as one: "1:15 PM today", "11:57 PM
yesterday", "9:05 AM on Mon, Sep 28" (the year only when it isn't this one).
"""

from datetime import date, datetime, tzinfo


def clock(t: datetime) -> str:
    """ "1:15 PM" (in the time's own zone). """
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def day(d: date, today: date) -> str:
    """ "today", "yesterday", else "on Mon, Sep 28" ("on Mon, Sep 28, 2025" in another year). """
    days = (today - d).days
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    year = f", {d.year}" if d.year != today.year else ""
    return f"on {d.strftime('%a')}, {d.strftime('%b')} {d.day}{year}"


def part_of_day(t: datetime) -> str:
    """ "morning" (5 AM-noon), "afternoon" (to 5 PM), "evening" (to 9 PM) or "night"; in the time's own zone. """
    return "morning" if 5 <= t.hour < 12 else "afternoon" if 12 <= t.hour < 17 else "evening" if 17 <= t.hour < 21 else "night"


def full(at: datetime, tz: tzinfo) -> str:
    """The whole moment, for a model to reason with: "Thursday, October 1, 2026, at 8:31 PM (evening)"."""
    local = at.astimezone(tz)
    return f"{local:%A}, {local:%B} {local.day}, {local.year}, at {clock(local)} ({part_of_day(local)})"


def spoken(at: datetime, tz: tzinfo, now: datetime | None = None) -> str:
    """When, for a sentence: "1:15 PM today", "11:57 PM yesterday", "9:05 AM on Mon, Sep 28"."""
    local = at.astimezone(tz)
    today = (now or datetime.now(tz)).astimezone(tz).date()
    return f"{clock(local)} {day(local.date(), today)}"
