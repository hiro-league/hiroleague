"""Counting times into slots (the Logs page's summary). Pure: no database."""

from collections.abc import Iterable
from datetime import datetime, timedelta


def slots(times: Iterable[datetime], start: datetime, size: timedelta, count: int) -> list[int]:
    """How many of `times` fall in each of `count` slots of `size` from `start` (oldest first).
    Times outside the slots are left out."""
    out = [0] * count
    for t in times:
        i = int((t - start) / size)
        if 0 <= i < count:
            out[i] += 1
    return out
