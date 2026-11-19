"""A part's own log file: one file a day, `<name>-<YYYY-MM-DD>.jsonl` in its logs folder, kept KEEP_DAYS days.
(A child process's raw output uses the same rule with `.log`: `<name>-<child>-<YYYY-MM-DD>.log`.)

The day is in the file's name, so nothing is ever renamed (on Windows a file a reader has open can't be), and a reader
knows which days a file holds without opening it. The day is the house's (local time); the lines inside say UTC.
At the first line of a new day the writer opens that day's file and deletes the files older than KEEP_DAYS days.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import IO

KEEP_DAYS = 30
SUFFIX = ".jsonl"
CHILD_SUFFIX = ".log"
_DAY = re.compile(r"^(?P<name>.+)-(?P<day>\d{4}-\d{2}-\d{2})(?P<suffix>\.[a-z]+)$")


def file_name(name: str, day: date, suffix: str = SUFFIX) -> str:
    return f"{name}-{day.isoformat()}{suffix}"


def day_of(path: Path, name: str, suffix: str = SUFFIX) -> date | None:
    """The day a file of `name` holds, or None when it isn't one of its daily files."""
    m = _DAY.match(path.name)
    if not m or m["name"] != name or m["suffix"] != suffix:
        return None
    try:
        return date.fromisoformat(m["day"])
    except ValueError:
        return None


def files(folder: Path, name: str, suffix: str = SUFFIX) -> list[tuple[date, Path]]:
    """`name`'s daily files in `folder`, newest first."""
    if not folder.is_dir():
        return []
    found = [(d, p) for p in folder.glob(f"{name}-*{suffix}") if (d := day_of(p, name, suffix)) is not None]
    return sorted(found, reverse=True)


def prune(folder: Path, name: str, today: date, keep_days: int = KEEP_DAYS, suffix: str = SUFFIX) -> list[Path]:
    """Delete `name`'s files older than `keep_days` days (today counts as one); the ones deleted."""
    oldest = today - timedelta(days=keep_days - 1)
    gone = []
    for d, path in files(folder, name, suffix):
        if d < oldest:
            try:
                path.unlink()
                gone.append(path)
            except OSError:
                pass  # in use or gone already: the next day tries again
    return gone


class DailyFile(logging.Handler):
    """Writes each record's line into the day's file. Runs on the foundation's writer thread (never a caller's), so
    it may wait on the disk without holding anything up."""

    def __init__(self, folder: Path, name: str, keep_days: int = KEEP_DAYS) -> None:
        super().__init__()
        self.folder = Path(folder)
        self.name_ = name
        self.keep_days = keep_days
        self._day: date | None = None
        self._stream: IO[str] | None = None

    @property
    def path(self) -> Path | None:
        return self.folder / file_name(self.name_, self._day) if self._day else None

    def _today(self) -> date:
        return datetime.now().date()

    def _open(self, day: date) -> None:
        if self._stream is not None:
            self._stream.close()
        self.folder.mkdir(parents=True, exist_ok=True)
        self._day = day
        self._stream = (self.folder / file_name(self.name_, day)).open("a", encoding="utf-8", newline="\n")
        prune(self.folder, self.name_, day, self.keep_days)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            today = self._today()
            if today != self._day or self._stream is None:
                self._open(today)
            assert self._stream is not None
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()  # a reader (the Logs page) reads the file as it grows
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self.acquire()
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self._day = None
        finally:
            self.release()
        super().close()
