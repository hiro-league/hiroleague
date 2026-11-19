"""The Logs page: what the app did and what went wrong, read from the files in DATA_DIR/logs (logfiles.py).

- `GET /api/logs`: the lines of a span (1 h / 24 h / 7 days), problems only or everything, of one source
  or all, newest first, each with its fields. Grouping repeats, areas and search are the page's.
- `GET /api/logs/summary`: the Overview card (errors and warnings in 24 h, the newest problem).
- `GET /api/logs/files`, `/api/logs/files/{name}`: the files (one a day, and crash.log), and one to download.

Open pages hear "logs" when the web app writes a line (at most every NOTIFY_EVERY seconds): the notifier
is a handler that only notes it, and a worker that tells the pages.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from hiro_channel_sdk.workers import Worker
from pydantic import BaseModel

from . import identity, logfiles
from .errors import NotFound
from .events import bus
from .logfiles import Entry, Level, Source
from .logs import CRASH_FILE, KEEP_DAYS, LOGGERS
from .timeline import slots

log = identity.logger("logs")
router = APIRouter(prefix="/api/logs")

SPANS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
_NAME = identity.app().name
SOURCES: tuple[Source, ...] = (_NAME, "crash")
# The `source` filter's values, built from the app's name as logfiles.Source is (see there)
if TYPE_CHECKING:
    SourceOrAll = str
else:
    SourceOrAll = Literal["all", _NAME, "crash"]
LIMIT = 3000  # lines per answer at most (newest first): Everything over 7 days can be far more
NOTIFY_EVERY = 3.0  # seconds

CRASH_WHAT = "hard crashes in native code"


class LogLineOut(BaseModel):
    id: str  # its file and line: stays the same until the file rotates
    at: str
    level: Level
    logger: str
    source: Source
    message: str
    detail: str | None  # the traceback
    fields: dict[str, str]  # the line's own fields (elapsed_ms, url, error...), as text


class LogsOut(BaseModel):
    lines: list[LogLineOut]
    more: bool  # there were more than LIMIT: the oldest aren't here
    unreadable: list[str]  # files that couldn't be read, and why


class LogHour(BaseModel):
    errors: int
    warnings: int


class LogSummaryOut(BaseModel):
    errors: int
    warnings: int
    newest: LogLineOut | None  # the latest problem
    hours: list[LogHour]  # the 24 hours, oldest first


class LogFileOut(BaseModel):
    name: str
    what: str
    day: str | None  # the day a daily file holds (ISO date); None for crash.log
    size: int  # bytes


class LogFilesOut(BaseModel):
    files: list[LogFileOut]  # newest first, crash.log last
    keep_days: int  # a daily file is kept this many days


def _text(v: object) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)


def _out(e: Entry) -> LogLineOut:
    detail = "\n".join(e.detail).rstrip()
    return LogLineOut.model_validate({
        "id": f"{e.file}:{e.line}", "at": e.at.isoformat(), "level": e.level, "logger": e.logger,
        "source": e.source, "message": e.message, "detail": detail or None,
        "fields": {k: _text(v) for k, v in e.fields.items()},
    })


@router.get("")
def get_lines(span: Literal["1h", "24h", "7d"] = "24h", view: Literal["problems", "all"] = "problems",
              source: SourceOrAll = "all",
              limit: int = Query(LIMIT, ge=1, le=LIMIT)) -> LogsOut:
    sources: list[Source] = list(SOURCES) if source == "all" else [source]
    found, unreadable = logfiles.entries(sources, view == "problems", datetime.now().astimezone() - SPANS[span])
    return LogsOut.model_validate({"lines": [_out(e) for e in found[:limit]], "more": len(found) > limit, "unreadable": unreadable})


@router.get("/summary")
def get_summary() -> LogSummaryOut:
    start = datetime.now().astimezone() - SPANS["24h"]
    found, _unreadable = logfiles.entries(list(SOURCES), True, start)
    errors = [e.at for e in found if e.level in ("ERROR", "CRITICAL")]
    warnings = [e.at for e in found if e.level == "WARNING"]
    by_hour = zip(slots(errors, start, timedelta(hours=1), 24), slots(warnings, start, timedelta(hours=1), 24), strict=True)
    return LogSummaryOut.model_validate({
        "errors": len(errors),
        "warnings": len(warnings),
        "newest": _out(found[0]) if found else None,
        "hours": [{"errors": e, "warnings": w} for e, w in by_hour],
    })


def _size(path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


@router.get("/files")
def get_files() -> LogFilesOut:
    out = [LogFileOut.model_validate({"name": path.name, "what": "the day's lines", "day": day.isoformat(), "size": _size(path)})
           for day, path in logfiles.files(_NAME)]
    crash = logfiles.FOLDER / CRASH_FILE
    out.append(LogFileOut.model_validate({"name": CRASH_FILE, "what": CRASH_WHAT, "day": None, "size": _size(crash)}))
    return LogFilesOut.model_validate({"files": out, "keep_days": KEEP_DAYS})


def _downloadable() -> set[str]:
    return {path.name for _day, path in logfiles.files(_NAME)} | {CRASH_FILE}


@router.get("/files/{name}")
def download(name: str) -> FileResponse:
    path = logfiles.FOLDER / name
    if name not in _downloadable() or not path.is_file():  # only these names: never a path of the caller's
        raise NotFound(f"No log file {name!r}")
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=name)


# --- telling open pages ---------------------------------------------------------------------------


class _Noted(logging.Handler):
    """Only notes that a line was written (a handler must be quick, and may run on any thread)."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.written = False

    def emit(self, record: logging.LogRecord) -> None:
        self.written = True


class LogNotifier(Worker):
    name = "logs"

    def __init__(self) -> None:
        super().__init__()
        self._noted = _Noted()

    def on_start(self) -> None:
        for name in LOGGERS:
            logging.getLogger(name).addHandler(self._noted)
        self.every(NOTIFY_EVERY, self._tell, "tell")

    def on_stop(self) -> None:
        for name in LOGGERS:
            logging.getLogger(name).removeHandler(self._noted)

    def _tell(self) -> None:
        if self._noted.written:
            self._noted.written = False
            bus.publish("logs")


notifier = LogNotifier()
