"""Reading the log files logs.py writes (DATA_DIR/logs), for the Logs page.

- `<app>.log` / `<app>-errors.log`: one line per entry, `2026-09-29 01:44:33+0300 WARNING nethiro.ha:
  message`; the lines after it that don't look like that (a traceback, the rest of a message) belong to it.
  Rotated copies are `.1` (newer) to `.5`.
- `crash.log`: faulthandler's reports of a hard crash, with no time at all.

A file is parsed once, then only what was added since (the current files grow all day); when another
file took its name (rotated) or it got smaller, it is read again from the start.
"""

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from . import identity
from .errors import failed
from .logs import KEEP

log = identity.logger("logs")

FOLDER = identity.app().data_dir / "logs"
# A log source is the app's own name ("nethiro") or "crash". The API's schema names the two values, as each app's
# own copy of this module did, so the pages' generated types don't change: the Literal is built from the app's name
# when the module loads; a type checker, which can't follow that, reads it as text.
if TYPE_CHECKING:
    Source = str
else:
    Source = Literal[identity.app().name, "crash"]
Level = Literal["INFO", "WARNING", "ERROR", "CRITICAL"]

LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[+-]\d{4}) (DEBUG|INFO|WARNING|ERROR|CRITICAL) (\S+): (.*)$")
CRASH = re.compile(r"^(Fatal Python error|Windows fatal exception|panic:|fatal error:)")


@dataclass
class Entry:
    at: datetime
    level: Level
    logger: str
    source: Source
    message: str
    file: str
    line: int  # where it starts in its file (1-based): with the file, its id
    detail: list[str] = field(default_factory=list)


@dataclass
class _Parsed:
    ino: int = 0  # which file it was: rotation renames it, and a new one takes its name
    size: int = 0  # bytes read so far (up to the last full line)
    lines: int = 0
    entries: list[Entry] = field(default_factory=list)
    error: str | None = None  # the last read failure, logged once


_cache: dict[Path, _Parsed] = {}
_lock = threading.Lock()  # routes run in worker threads


def files(source: Source, problems: bool) -> list[Path]:
    """A source's files, newest first: the current one, then its rotated copies."""
    if source == "crash":
        return [FOLDER / "crash.log"]
    base = FOLDER / (f"{source}-errors.log" if problems else f"{source}.log")
    return [base, *(base.with_name(f"{base.name}.{i}") for i in range(1, KEEP + 1))]


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
        if st.st_ino != cached.ino or size < cached.size:  # another file now (rotated), or emptied: from the start
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
    last = into.entries[-1] if into.entries else None
    for raw in text.splitlines():
        into.lines += 1
        line = raw.rstrip("\r")
        m = LINE.match(line) if source != "crash" else None
        if m:
            last = Entry(datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S%z"), _level(m[2]), m[3], source, m[4], path.name, into.lines)
            into.entries.append(last)
        elif source == "crash" and CRASH.match(line):
            last = Entry(_mtime(path), "CRITICAL", "crash", source, line, path.name, into.lines)
            into.entries.append(last)
        elif last is not None and (line or last.detail):
            last.detail.append(line)
    for e in into.entries:  # (a crash report says no time: the file's is the best there is)
        if source == "crash":
            e.at = _mtime(path)


def _level(name: str) -> Level:
    return "WARNING" if name == "WARNING" else "ERROR" if name == "ERROR" else "CRITICAL" if name == "CRITICAL" else "INFO"


def _mtime(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    except OSError:
        return datetime.now().astimezone()


def entries(sources: list[Source], problems: bool, since: datetime) -> tuple[list[Entry], list[str]]:
    """Every entry of these sources since `since`, newest first, and the files that couldn't be read."""
    found: list[Entry] = []
    unreadable: list[str] = []
    for source in sources:
        for path in files(source, problems):
            got, error = read(path, source)
            if error:
                unreadable.append(error)
            found += [e for e in got if e.at >= since and (not problems or e.level != "INFO")]
            if got and got[0].at < since:  # this file goes back far enough: the older copies are older still
                break
    found.sort(key=lambda e: e.at, reverse=True)
    return found, unreadable


def forget() -> None:
    """Drop what was parsed (tests)."""
    with _lock:
        _cache.clear()
