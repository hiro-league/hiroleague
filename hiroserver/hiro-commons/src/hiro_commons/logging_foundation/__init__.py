"""The logging foundation: one setup for a process, so every part of Hiro League logs the same way.

    from hiro_commons import logging_foundation
    logging_foundation.setup(data_dir / "logs", name="homehiro", service="home")

What a process gets:
- **Standard Python logging is the front door.** Code logs with `logging.getLogger("<app>.<area>")`; libraries do
  already. Code written for structlog (the SDK's link to the core, the memory library) is wired into it (bridge.py).
- **The line's shape:** one JSON object per line with OpenTelemetry's log field names (line.py).
- **Its own file:** `<folder>/<name>-<YYYY-MM-DD>.jsonl`, one a day, kept 30 days (daily.py).
- **A level per area:** INFO for every area unless `levels` (or the LOG_LEVELS setting: `homehiro.ha=DEBUG,
  EXTENSION=WARNING`) says otherwise for an area; an area's level holds for the areas under it.
- **Logging never blocks a request:** a caller only puts its record on a queue; one writer thread writes the file and
  the console (the standard library's QueueHandler and QueueListener).
- **Nothing that goes wrong escapes the file (the safety nets):**
  - an exception nobody caught, in the main thread or any other;
  - one nobody could raise (a failing __del__ or callback);
  - an asyncio task that failed and was never awaited (`watch_loop()`, on each event loop: the backend kit calls it
    from `events.bind()`);
  - Python warnings;
  - every library's warnings and errors, with their tracebacks;
  - the web server's own lines (uvicorn's loggers don't pass them to the root logger);
  - a hard crash in native code (faulthandler writes every thread's stack to `crash.log`);
  - a child process's own output and crash (`child_log()`: its own daily file).
  `self_test()` (selftest.py) raises each kind of failure and checks it reached the file; every app's contract runs it.
- **The console** (`docker logs`) keeps a short line per record, for watching a process start.

Third-party libraries that are chatty at INFO (QUIET) are held back to WARNING.

The core's own logger (hiro_commons.log) is untouched by this: the core moves onto the foundation in a later phase.
"""

from __future__ import annotations

import asyncio
import atexit
import faulthandler
import logging
import os
import queue
import sys
import threading
from datetime import datetime
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Mapping

from . import bridge, daily, line
from .daily import KEEP_DAYS, DailyFile
from .line import Line, parse

__all__ = ["setup", "close", "where", "flush", "watch_loop", "child_log", "self_test", "levels_from", "Line", "parse", "daily", "line", "KEEP_DAYS", "LOGGERS", "CRASH_FILE"]

LOGGERS = ("", "uvicorn")  # the root logger, and uvicorn's, which keeps its lines to itself (not its access log)
QUIET = {"httpx": logging.WARNING, "httpcore": logging.WARNING}  # httpx logs every request at INFO
CONSOLE_FORMAT = "%(levelname)s:     %(name)s: %(message)s"  # uvicorn's look
CRASH_FILE = "crash.log"
LEVELS_SETTING = "LOG_LEVELS"

log = logging.getLogger("hiro.logging")  # setup() names it after the process: `<name>.logs`


class _State:
    listener: QueueListener | None = None
    front: "_Front | None" = None
    file: DailyFile | None = None
    crash_file: IO[str] | None = None
    levels: dict[str, int] = {}
    hooks: tuple | None = None
    root_level: int | None = None


_state = _State()


class _Front(QueueHandler):
    """What a caller's thread does with a record: build its line and put it on the queue. Building the line here (not
    on the writer thread) keeps the exception and the fields as they were when it was logged."""

    def __init__(self, q: queue.SimpleQueue, service: str) -> None:
        super().__init__(q)
        self.service = service

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        built = line.build(record, self.service)
        copy = logging.makeLogRecord(record.__dict__)
        copy.hiro_line = line.render(built)  # type: ignore[attr-defined]
        copy.msg, copy.args = built["Body"], None
        copy.hiro_fields = built.get("Attributes", {})  # type: ignore[attr-defined]
        copy.exc_text = built.get("Attributes", {}).get("exception.stacktrace") or record.exc_text
        copy.exc_info = None  # a traceback can't cross threads safely; its text did
        return copy


class _FileFormat(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return getattr(record, "hiro_line", None) or line.render(line.build(record, ""))


class _ConsoleFormat(logging.Formatter):
    """uvicorn's look, with the line's fields after the sentence (the link's lines say most in their fields)."""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        fields = {k: v for k, v in (getattr(record, "hiro_fields", None) or {}).items() if not k.startswith(("exception.", "code."))}
        if fields:
            head, sep, rest = text.partition("\n")
            text = head + " · " + " · ".join(f"{k}={v}" for k, v in fields.items()) + sep + rest
        return text


def levels_from(text: str | None) -> dict[str, str]:
    """`homehiro.ha=DEBUG, EXTENSION=WARNING` → {"homehiro.ha": "DEBUG", "EXTENSION": "WARNING"}."""
    out: dict[str, str] = {}
    for part in (text or "").split(","):
        area, sep, level = part.partition("=")
        if sep and area.strip() and level.strip():
            out[area.strip()] = level.strip().upper()
    return out


def setup(folder: Path, *, name: str, service: str, levels: Mapping[str, str] | None = None, console: bool = True,
          keep_days: int = KEEP_DAYS) -> Path:
    """Set up this process's logging (again: replaces the first setup, writes nothing twice). `name` names the files
    (`homehiro-2026-11-19.jsonl`); `service` is the process in each line (`home`). The file of today, once written."""
    global log
    close()
    log = logging.getLogger(f"{name}.logs")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    q: queue.SimpleQueue = queue.SimpleQueue()
    front = _Front(q, service)
    file = DailyFile(folder, name, keep_days)
    file.setFormatter(_FileFormat())
    writers: list[logging.Handler] = [file]
    root = logging.getLogger()
    if console and not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
                           for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(_ConsoleFormat(CONSOLE_FORMAT))
        writers.append(stream)
    listener = QueueListener(q, *writers, respect_handler_level=True)
    listener.start()
    _state.listener, _state.front, _state.file = listener, front, file
    _state.root_level = root.level
    root.setLevel(logging.INFO)
    for logger_name in LOGGERS:
        logging.getLogger(logger_name).addHandler(front)
    for noisy, level in QUIET.items():
        logging.getLogger(noisy).setLevel(level)
    wanted = {**levels_from(os.environ.get(LEVELS_SETTING)), **(levels or {})}
    _state.levels = {}
    for area, level in wanted.items():
        number = logging.getLevelName(level.upper())
        if isinstance(number, int):
            logging.getLogger(area).setLevel(number)
            _state.levels[area] = number
        else:
            log.warning("Logging: unknown level %r for %s (DEBUG, FINEINFO, INFO, WARNING, ERROR, CRITICAL)", level, area)
    bridge.wire()
    logging.captureWarnings(True)
    _state.hooks = (sys.excepthook, threading.excepthook, sys.unraisablehook)
    sys.excepthook = _uncaught
    threading.excepthook = _uncaught_in_thread
    sys.unraisablehook = _unraisable
    _catch_crashes(folder / CRASH_FILE)
    return folder / daily.file_name(name, file._today())


def flush() -> None:
    """Wait until every line logged so far is in the file (the writer thread drains the queue, then starts again)."""
    listener = _state.listener
    if listener is not None:
        listener.stop()
        listener.start()


def _loop_failed(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """An event loop's error nobody could catch: mostly a task that failed and was never awaited ("Task exception was
    never retrieved"), or a callback that raised. Logged with its traceback and which task it was."""
    exc = context.get("exception")
    task = context.get("task") or context.get("future")
    fields: dict[str, Any] = {}
    if task is not None:
        fields["task"] = task.get_name() if isinstance(task, asyncio.Task) else repr(task)[:200]
        coro = task.get_coro() if isinstance(task, asyncio.Task) else None
        if coro is not None:
            fields["coroutine"] = getattr(coro, "__qualname__", repr(coro))[:200]
    if context.get("handle") is not None:
        fields["callback"] = repr(context["handle"])[:200]
    logging.getLogger("asyncio").error("%s", context.get("message") or "Event loop error",
                                       exc_info=(type(exc), exc, exc.__traceback__) if isinstance(exc, BaseException) else None,
                                       extra={line.ATTRIBUTES: fields})


def watch_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Log every error of this event loop that nothing could catch (the running loop when none is given)."""
    (loop or asyncio.get_running_loop()).set_exception_handler(_loop_failed)


def child_log(child: str) -> IO[str]:
    """A file for a child process's own output (its stdout and stderr, a crash's last words included):
    `<name>-<child>-<YYYY-MM-DD>.log` beside the process's own file, one a day, kept as long. Pass it as the child's
    `stdout` and `stderr`; close it when the child is done."""
    if _state.file is None:
        raise RuntimeError("logging_foundation.child_log() before setup()")
    folder, name = _state.file.folder, f"{_state.file.name_}-{child}"
    today = datetime.now().date()
    daily.prune(folder, name, today, _state.file.keep_days, daily.CHILD_SUFFIX)
    return (folder / daily.file_name(name, today, daily.CHILD_SUFFIX)).open("a", encoding="utf-8")


def self_test(startup: Any = None) -> dict[str, bool]:
    """Raise each kind of failure and check that it reached the file (selftest.py)."""
    from .selftest import run

    return run(startup)


def where() -> tuple[Path, str] | None:
    """The folder and the name this process's files are written with, once set up."""
    f = _state.file
    return (f.folder, f.name_) if f is not None else None


def close() -> None:
    """Write what is queued, close the files and put the process back as it was (tests; at exit by itself)."""
    if _state.front is not None:
        for logger_name in LOGGERS:
            logging.getLogger(logger_name).removeHandler(_state.front)
        _state.front.close()
        _state.front = None
    if _state.listener is not None:
        _state.listener.stop()  # writes everything still queued first
        for h in _state.listener.handlers:
            h.close()
        _state.listener = None
    _state.file = None
    for area in _state.levels:
        logging.getLogger(area).setLevel(logging.NOTSET)
    _state.levels = {}
    if _state.root_level is not None:
        logging.getLogger().setLevel(_state.root_level)
        _state.root_level = None
    bridge.unwire()
    if _state.hooks is not None:
        sys.excepthook, threading.excepthook, sys.unraisablehook = _state.hooks
        _state.hooks = None
        logging.captureWarnings(False)
    if _state.crash_file is not None:
        faulthandler.disable()
        _state.crash_file.close()
        _state.crash_file = None


atexit.register(close)


def _catch_crashes(path: Path) -> None:
    _state.crash_file = path.open("a", encoding="utf-8")  # kept open: a crash can't open a file any more
    faulthandler.enable(_state.crash_file, all_threads=True)


def _uncaught(kind: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    if issubclass(kind, KeyboardInterrupt):
        sys.__excepthook__(kind, exc, tb)
        return
    log.critical("Uncaught exception: %s", exc, exc_info=(kind, exc, tb))


def _unraisable(args: "sys.UnraisableHookArgs") -> None:
    log.error("Unraisable exception (%s): %s", args.err_msg or "in", args.exc_value,
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback) if args.exc_value else None)


def _uncaught_in_thread(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit or args.exc_value is None:
        return
    name = args.thread.name if args.thread else "?"
    log.error("Uncaught exception in thread %s: %s", name, args.exc_value,
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
