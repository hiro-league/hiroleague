"""Logs: what the app did and what went wrong, kept in files that survive restarts and deploys.

The console (`docker logs`) is lost whenever the container is replaced, which every deploy does, and it
mixes problems with everything else. So the web app also writes DATA_DIR/logs:
- `<app>.log` (the app's name, identity.py: `nethiro.log`): everything at INFO and above;
- `<app>-errors.log`: WARNING and above only, so problems are found without reading the rest.
Files rotate (ROTATE_BYTES, KEEP old files each), so the folder never grows past about 150 MB.

Also written here, not only to the console, so nothing that goes wrong escapes the files
(each app's docs/backend-best-practices.md, section 5):
- uvicorn's own lines, a request that crashed included ("Exception in ASGI application"): uvicorn's
  loggers don't pass their lines on to the root logger;
- an exception nobody caught, in the main thread or any other (sys and threading excepthooks), and one
  nobody could raise (sys.unraisablehook: a failing __del__ or callback); exceptions in asyncio tasks
  reach the "asyncio" logger by themselves;
- Python warnings (logging.captureWarnings: the "py.warnings" logger);
- a hard crash in native code (ONNX, OpenCV): faulthandler writes every
  thread's Python stack to `crash.log`.
Third-party libraries log through the root logger too; QUIET holds back the ones that are chatty at INFO.
"""

import faulthandler
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import IO

from . import identity

CONSOLE_FORMAT = "%(levelname)s:     %(name)s: %(message)s"  # as before: uvicorn's look
FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S%z"
ROTATE_BYTES = {"all": 10_000_000, "errors": 5_000_000}
KEEP = 5
LOGGERS = ("", "uvicorn")  # the root logger, and uvicorn's, which keeps its lines to itself (not its access log)
QUIET = {"httpx": logging.WARNING, "httpcore": logging.WARNING}  # httpx logs every request at INFO

_crash_file: IO[str] | None = None

log = identity.logger("logs")


class _Ours:
    """Marks the handlers setup() adds, so a second call replaces them instead of adding more."""


class _FileHandler(RotatingFileHandler, _Ours):
    pass


class _ConsoleHandler(logging.StreamHandler, _Ours):
    pass


def setup(folder: Path, console: bool = True) -> None:
    """Log INFO and above to the console (unless `console` is False: something else already does) and
    to the files in `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    name = identity.app().name  # the files are the app's: nethiro.log, nethiro-errors.log
    everything = _FileHandler(folder / f"{name}.log", maxBytes=ROTATE_BYTES["all"], backupCount=KEEP,
                              encoding="utf-8", delay=True)
    errors = _FileHandler(folder / f"{name}-errors.log", maxBytes=ROTATE_BYTES["errors"], backupCount=KEEP,
                          encoding="utf-8", delay=True)
    errors.setLevel(logging.WARNING)
    for h in (everything, errors):
        h.setFormatter(logging.Formatter(FILE_FORMAT, DATE_FORMAT))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for logger_name in LOGGERS:
        logger = logging.getLogger(logger_name)
        for old in [h for h in logger.handlers if isinstance(h, _Ours)]:
            logger.removeHandler(old)
            old.close()
        logger.addHandler(everything)
        logger.addHandler(errors)
    if console and not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
                           for h in root.handlers):
        stream = _ConsoleHandler()
        stream.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        root.addHandler(stream)
    for noisy, level in QUIET.items():
        logging.getLogger(noisy).setLevel(level)
    logging.captureWarnings(True)
    sys.excepthook = _uncaught
    threading.excepthook = _uncaught_in_thread
    sys.unraisablehook = _unraisable
    _catch_crashes(folder / "crash.log")


def close() -> None:
    """Close the files (the tests do, before deleting their folder; Windows can't delete an open file)."""
    global _crash_file
    for logger_name in LOGGERS:
        logger = logging.getLogger(logger_name)
        for h in [h for h in logger.handlers if isinstance(h, _Ours)]:
            logger.removeHandler(h)
            h.close()
    if _crash_file is not None:
        faulthandler.disable()
        _crash_file.close()
        _crash_file = None


def _catch_crashes(path: Path) -> None:
    global _crash_file
    if _crash_file is not None:
        faulthandler.disable()
        _crash_file.close()
    _crash_file = path.open("a", encoding="utf-8")  # kept open: a crash can't open a file any more
    faulthandler.enable(_crash_file, all_threads=True)


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
