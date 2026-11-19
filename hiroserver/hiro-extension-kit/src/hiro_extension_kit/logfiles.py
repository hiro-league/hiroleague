"""Reading the log files logs.py writes (DATA_DIR/logs), for the Logs page.

- `<app>-<YYYY-MM-DD>.jsonl`: one file a day, one JSON line per entry (hiro_commons.logging_foundation.line: its
  time, level, area, sentence, fields and traceback). A line that isn't one (half written, or foreign) is skipped.
- `crash.log`: faulthandler's reports of a hard crash, with no time at all.

A file is parsed once, then only what was added since (today's file grows all day); when another file took its name
or it got smaller, it is read again from the start. A day's file is read only when the span reaches its day.
"""

import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from hiro_commons.logging_foundation import daily, line

from . import identity
from .errors import failed
from .logs import CRASH_FILE

log = identity.logger("logs")

FOLDER = identity.app().data_dir / "logs"
# A log source is the app's own name ("nethiro") or "crash". The API's schema names the two values, as each app's
# own copy of this module did, so the pages' generated types don't change: the Literal is built from the app's name
# when the module loads; a type checker, which can't follow that, reads it as text.
if TYPE_CHECKING:
    Source = str
else:
    Source = Literal[identity.app().name, "crash"]
Level = Literal["DEBUG", "FINEINFO", "INFO", "WARNING", "ERROR", "CRITICAL"]
_LEVELS = {"DEBUG", "FINEINFO", "INFO", "WARNING", "ERROR", "CRITICAL"}
PROBLEM = 13  # SeverityNumber: WARN and up

CRASH = re.compile(r"^(Fatal Python error|Windows fatal exception|panic:|fatal error:)")


@dataclass
class Entry:
    at: datetime
    level: Level
    logger: str
    source: Source
    message: str
    file: str
    line: int  # where it is in its file (1-based): with the file, its id
    detail: list[str] = field(default_factory=list)  # the traceback, a line each
    fields: dict[str, Any] = field(default_factory=dict)
    number: int = 9  # SeverityNumber

    @property
    def problem(self) -> bool:
        return self.number >= PROBLEM


@dataclass
class _Parsed:
    ino: int = 0  # which file it was: a new one can take its name
    size: int = 0  # bytes read so far (up to the last full line)
    lines: int = 0
    entries: list[Entry] = field(default_factory=list)
    error: str | None = None  # the last read failure, logged once


_cache: dict[Path, _Parsed] = {}
_lock = threading.Lock()  # routes run in worker threads


def files(source: Source) -> list[tuple[date | None, Path]]:
    """A source's files, newest first, each with the day it holds (None: any day)."""
    if source == "crash":
        return [(None, FOLDER / CRASH_FILE)]
    return [(d, p) for d, p in daily.files(FOLDER, source)]


def read(path: Path, source: Source) -> tuple[list[Entry], str | None]:
    """The file's entries (oldest first), and why it couldn't be read, if it couldn't."""
    with _lock:
        cached = _cache.setdefault(path, _Parsed())
        try:
            st = path.stat()
        except FileNotFoundError:
            _cache.pop(path, None)
            return [], None
        except OSError as exc:
            return cached.entries, _unreadable(path, cached, exc)
        size = st.st_size
        if st.st_ino != cached.ino or size < cached.size:  # another file now, or emptied: from the start
            cached = _cache[path] = _Parsed(ino=st.st_ino)
        if size > cached.size:
            try:
                with path.open("rb") as f:
                    f.seek(cached.size)
                    chunk = f.read(size - cached.size)
            except OSError as exc:
                return cached.entries, _unreadable(path, cached, exc)
            end = chunk.rfind(b"\n") + 1  # a line still being written is read next time
            text = chunk[:end].decode("utf-8", "replace")
            cached.size += end
            if source == "crash":
                _parse_crash(text, path, cached)
            else:
                _parse(text, source, path, cached)
        cached.error = None
        return cached.entries, None


def _unreadable(path: Path, cached: _Parsed, exc: OSError) -> str:
    reason = f"{path.name} can't be read ({type(exc).__name__}: {exc})"
    if cached.error != reason:  # once: this log line is itself read by the page, which asks again
        failed(log, f"Logs: reading {path.name}", exc)
        cached.error = reason
    return reason


def _parse(text: str, source: Source, path: Path, into: _Parsed) -> None:
    for raw in text.splitlines():
        into.lines += 1
        got = line.parse(raw)
        if got is None:
            continue
        level: Any = got.level if got.level in _LEVELS else "INFO"
        into.entries.append(Entry(got.at, level, got.scope, source, got.body, path.name, into.lines,
                                  (got.stacktrace or "").splitlines(), got.fields, got.number))


def _parse_crash(text: str, path: Path, into: _Parsed) -> None:
    last = into.entries[-1] if into.entries else None
    for raw in text.splitlines():
        into.lines += 1
        row = raw.rstrip("\r")
        if CRASH.match(row):
            last = Entry(_mtime(path), "CRITICAL", "crash", "crash", row, path.name, into.lines, number=21)
            into.entries.append(last)
        elif last is not None and (row or last.detail):
            last.detail.append(row)
    for e in into.entries:  # a crash report says no time: the file's is the best there is
        e.at = _mtime(path)


def _mtime(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    except OSError:
        return datetime.now().astimezone()


def entries(sources: list[Source], problems: bool, since: datetime) -> tuple[list[Entry], list[str]]:
    """Every entry of these sources since `since`, newest first, and the files that couldn't be read."""
    found: list[Entry] = []
    unreadable: list[str] = []
    first_day = since.astimezone().date()  # the files are named by the house's day
    for source in sources:
        for day, path in files(source):
            if day is not None and day < first_day:
                break  # newest first: the rest are older still
            got, error = read(path, source)
            if error:
                unreadable.append(error)
            found += [e for e in got if e.at >= since and (not problems or e.problem)]
    found.sort(key=lambda e: e.at, reverse=True)
    return found, unreadable


def forget() -> None:
    """Drop what was parsed (tests)."""
    with _lock:
        _cache.clear()
