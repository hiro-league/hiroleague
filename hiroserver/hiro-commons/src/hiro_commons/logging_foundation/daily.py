"""A part's own log file: one file a day, `<name>-<YYYY-MM-DD>.jsonl` in its logs folder, kept KEEP_DAYS days in plain
files, then KEEP_MONTHS months in a compressed archive. (A child process's raw output uses the same rule with `.log`:
`<name>-<child>-<YYYY-MM-DD>.log`.)

The day is in the file's name, so nothing is ever renamed (on Windows a file a reader has open can't be), and a reader
knows which days a file holds without opening it. The day is the house's (local time); the lines inside say UTC.
At the first line of a new day the writer opens that day's file and moves the files older than KEEP_DAYS days into the
archive: `archive/<name>-<YYYY-MM>.jsonl.gz` in the logs folder, one file a month, each day added to it as one more
gzip member (a gzip reader reads them as one stream, in the order they were added). Archives older than KEEP_MONTHS
months are deleted. The archive folder is what the nightly backup keeps of a part's logs.
"""

from __future__ import annotations

import gzip
import logging
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import IO

KEEP_DAYS = 30
KEEP_MONTHS = 12
SUFFIX = ".jsonl"
CHILD_SUFFIX = ".log"
ARCHIVE = "archive"
_DAY = re.compile(r"^(?P<name>.+)-(?P<day>\d{4}-\d{2}-\d{2})(?P<suffix>\.[a-z]+)$")
_MONTH = re.compile(r"^(?P<name>.+)-(?P<month>\d{4}-\d{2})(?P<suffix>\.[a-z]+)\.gz$")
log = logging.getLogger("hiro.logging.daily")


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


def archive_name(name: str, month: date, suffix: str = SUFFIX) -> str:
    return f"{name}-{month.strftime('%Y-%m')}{suffix}.gz"


def archives(folder: Path, name: str, suffix: str = SUFFIX) -> list[tuple[date, Path]]:
    """`name`'s monthly archives (the first of their month, and the file), newest first."""
    where = folder / ARCHIVE
    if not where.is_dir():
        return []
    found = []
    for p in where.glob(f"{name}-*{suffix}.gz"):
        m = _MONTH.match(p.name)
        if m and m["name"] == name and m["suffix"] == suffix:
            try:
                found.append((date.fromisoformat(m["month"] + "-01"), p))
            except ValueError:
                continue
    return sorted(found, reverse=True)


def _months_back(day: date, months: int) -> date:
    """The first of the month `months` months before `day`'s month."""
    total = day.year * 12 + (day.month - 1) - months
    return date(total // 12, total % 12 + 1, 1)


def prune(folder: Path, name: str, today: date, keep_days: int = KEEP_DAYS, suffix: str = SUFFIX,
          keep_months: int = KEEP_MONTHS) -> list[Path]:
    """Move `name`'s files older than `keep_days` days (today counts as one) into their month's archive, then delete
    the archives older than `keep_months` months; the day files moved."""
    oldest = today - timedelta(days=keep_days - 1)
    moved = []
    for d, path in sorted(files(folder, name, suffix)):  # oldest first: a month's members stay in order
        if d >= oldest:
            continue
        target = folder / ARCHIVE / archive_name(name, d, suffix)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with path.open("rb") as src, gzip.open(target, "ab") as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
            moved.append(path)
        except OSError as exc:
            # In use (Windows) or gone already: the next day tries again. A member written twice (the copy done, the
            # delete refused) is the one cost, and only on a retry.
            log.warning("Logs: couldn't archive %s (%s); trying again tomorrow", path.name, exc)
    first_kept = _months_back(today, keep_months - 1)
    for month, path in archives(folder, name, suffix):
        if month < first_kept:
            try:
                path.unlink()
            except OSError as exc:
                log.warning("Logs: couldn't delete the old archive %s (%s)", path.name, exc)
    return moved


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
        return datetime.now().astimezone().date()  # the house's day (the lines say UTC)

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
