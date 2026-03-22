"""Shared Hiro structured logging.

Two-step initialisation
-----------------------
1. ``Logger.set_level("DEBUG")``  — store the desired level (idempotent).
2. ``Logger.setup(console=True)`` — wire the structlog pipeline (one-time).

Order matters: *set_level before setup*.  Calling ``set_level`` multiple
times is harmless — last call wins.

Module-prefix routing
---------------------
File sinks support ``include_prefix`` / ``exclude_prefix`` filters so that
events are routed to the correct log file without any per-call boilerplate:

* ``CLI.*`` modules  →  ``cli.log``
* Everything else    →  ``server.log``

Channel plugins run in separate processes, each with their own
``channel-<name>.log`` created by ``log_setup.init()``.

``Logger.open_log_dir(log_dir)`` opens both routed sinks in one call
and is idempotent — safe to call from both the CLI callback and the
server startup path.
"""

from __future__ import annotations

import contextvars
import csv
import datetime
import io
import logging
import logging.handlers
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Mapping

import colorama
import structlog

from .constants.timing import LOG_ROTATION_BACKUP_COUNT, LOG_ROTATION_MAX_BYTES

colorama.init(autoreset=True)

# ---------------------------------------------------------------------------
# Custom FINEINFO level (15) — between DEBUG (10) and INFO (20).
# Registered early so both stdlib and structlog see it before any logger
# is created.
# ---------------------------------------------------------------------------
FINEINFO = 15
logging.addLevelName(FINEINFO, "FINEINFO")

# Patch structlog's internal level dicts so make_filtering_bound_logger
# generates a .fineinfo() / .afineinfo() method and the level is recognised
# everywhere inside the structlog pipeline.
import structlog._log_levels as _sl_levels  # noqa: E402
import structlog._native as _sl_native  # noqa: E402

_sl_levels.NAME_TO_LEVEL["fineinfo"] = FINEINFO
_sl_levels.LEVEL_TO_NAME[FINEINFO] = "fineinfo"

# Rebuild ALL filtering logger classes so every min_level variant
# (Debug, Info, …) gains the new .fineinfo() / .afineinfo() methods.
for _lvl in list(_sl_native.LEVEL_TO_FILTERING_LOGGER):
    _sl_native.LEVEL_TO_FILTERING_LOGGER[_lvl] = (
        _sl_native._make_filtering_bound_logger(_lvl)
    )
# Also add the new level's own entry.
_sl_native.LEVEL_TO_FILTERING_LOGGER[FINEINFO] = (
    _sl_native._make_filtering_bound_logger(FINEINFO)
)

# PrintLogger (structlog's default logger factory) dispatches via
# getattr(self, method_name) — it only defines msg/debug/info/warning/
# error/critical/fatal as aliases for msg.  Custom levels need an
# explicit alias so _proxy_to_logger("fineinfo", ...) doesn't raise
# AttributeError on the underlying PrintLogger instance.
structlog.PrintLogger.fineinfo = structlog.PrintLogger.msg  # type: ignore[attr-defined]

__all__ = [
    "FINEINFO",
    "Logger",
    "setup",
    "get_logger",
    "set_level",
    "set_module_levels",
    "disable",
    "enable",
]

_LEVEL_ABBREV = {
    "DEBUG": "DBG",
    "FINEINFO": "FNI",
    "INFO": "INF",
    "WARNING": "WRN",
    "ERROR": "ERR",
    "CRITICAL": "CRT",
}

_LEVEL_COLORS = {
    "DEBUG": colorama.Fore.BLUE,
    "FINEINFO": colorama.Fore.CYAN,
    "INFO": colorama.Fore.GREEN,
    "WARNING": colorama.Fore.YELLOW,
    "ERROR": colorama.Fore.RED,
    "CRITICAL": colorama.Fore.MAGENTA,
}

_MODULE_PALETTE = [
    colorama.Fore.CYAN,
    colorama.Fore.MAGENTA,
    colorama.Fore.YELLOW,
    colorama.Fore.GREEN,
]

_INDENT_LEVEL: contextvars.ContextVar[int] = contextvars.ContextVar(
    "indent_level", default=0
)
_INDENT_UNIT: str = "--"

_LEVELS: Mapping[str, int] = {
    name: level for name, level in logging._nameToLevel.items()
}

# (min_level, handler, renderer, include_prefix, exclude_prefixes)
_FILE_SINKS: list[tuple[int, logging.Handler, object, str | None, tuple[str, ...] | None]] = []
_MODULE_OVERRIDES: dict[str, int] = {}


def _resolve_level(level: str | int | None) -> int:
    if level is None:
        return logging.INFO
    if isinstance(level, int):
        return level
    return _LEVELS.get(str(level).upper(), logging.INFO)


def _pick_module_color(name: str) -> str:
    if not name:
        return colorama.Fore.WHITE
    index = sum(ord(c) for c in name) % len(_MODULE_PALETTE)
    return _MODULE_PALETTE[index]


def _epoch_to_time_str(epoch: float | str) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(epoch)).strftime("%H:%M:%S")
    except Exception:
        return str(epoch)


class _ColourRenderer:
    def __call__(self, logger, method_name, event_dict):
        ts = _epoch_to_time_str(event_dict.pop("ts", 0))
        level = event_dict.pop("level", "").upper()
        module = event_dict.pop("module", "")
        module_raw = module
        if len(module_raw) > 12:
            module_disp = module_raw[:12]
        else:
            module_disp = module_raw.ljust(12, "_")

        message = event_dict.pop("event", "")
        indent_level: int = _INDENT_LEVEL.get()
        indent_prefix = _INDENT_UNIT * max(indent_level, 0)
        if indent_prefix:
            message = f"{indent_prefix}{message}"

        lvl_abbr = _LEVEL_ABBREV.get(level, level[:3])
        lvl_color = _LEVEL_COLORS.get(level, colorama.Fore.WHITE)
        module_color = _pick_module_color(module)
        kv_str = " ".join(f"{k}={v}" for k, v in event_dict.items())

        parts = [
            f"{colorama.Style.DIM}[{ts}]",
            f"{lvl_color}[{lvl_abbr}]",
            f"{module_color}[{module_disp}]",
            colorama.Style.RESET_ALL + message,
        ]

        if kv_str:
            parts.append(colorama.Style.DIM + " " + kv_str)
        parts.append(colorama.Style.RESET_ALL)
        return " ".join(parts)


class _PlainRenderer:
    def __call__(self, logger, method_name, event_dict):
        ts = _epoch_to_time_str(event_dict.pop("ts", 0))
        level = event_dict.pop("level", "").upper()
        module = event_dict.pop("module", "")
        module_raw = module
        if len(module_raw) > 12:
            module_disp = module_raw[:12]
        else:
            module_disp = module_raw.ljust(12, "_")

        message = event_dict.pop("event", "")
        indent_level: int = _INDENT_LEVEL.get()
        indent_prefix = _INDENT_UNIT * max(indent_level, 0)
        if indent_prefix:
            message = f"{indent_prefix}{message}"

        lvl_abbr = _LEVEL_ABBREV.get(level, level[:3])
        kv_str = " ".join(f"{k}={v}" for k, v in event_dict.items())

        parts = [
            f"[{ts}]",
            f"[{lvl_abbr}]",
            f"[{module_disp}]",
            message,
        ]
        if kv_str:
            parts.append(" " + kv_str)
        return " ".join(parts)


class _CsvRenderer:
    """Renders log events as CSV rows for structured file logging.

    Columns: timestamp,level,module,message,extra
    timestamp is a Unix epoch float (e.g. 1742312005.437821) — gives
    sub-second precision for correct ordering of same-second events.
    Extra contains remaining key=value pairs joined by spaces.
    A CSV header line is written once when the file sink is first opened.
    """

    HEADER = "timestamp,level,module,message,extra"

    def __call__(self, logger, method_name, event_dict):
        ts = event_dict.pop("ts", 0)
        level = event_dict.pop("level", "").upper()
        module = event_dict.pop("module", "")
        message = event_dict.pop("event", "")
        extra = " ".join(f"{k}={v}" for k, v in event_dict.items())

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([ts, level, module, message, extra])
        return buf.getvalue().rstrip("\r\n")


class _NullRenderer:
    """Discards all console output; used when console=False."""

    def __call__(self, logger, method_name, event_dict):
        raise structlog.DropEvent()


class _StdlibBridge(logging.Handler):
    """Bridge stdlib logging records into the Hiro structured logger.

    Used by ``silence_stdlib()`` for per-library overrides with a fixed
    module tag.
    """

    def __init__(self, module: str, level: int = logging.WARNING):
        super().__init__(level)
        self._module = module

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log = structlog.get_logger(module=self._module)
            level = record.levelname.lower()
            log_method = getattr(log, level, log.warning)
            log_method(record.getMessage(), stdlib_logger=record.name)
        except Exception:
            pass


class _StdlibCatchAll(logging.Handler):
    """Catch-all bridge on the stdlib root logger.

    Installed by ``Logger.setup()`` to capture WARNING+ from *any*
    third-party library and re-emit through the structlog pipeline with
    proper formatting and file-sink routing.  The module tag is derived
    from the top-level package name (e.g. ``httpcore.connection`` →
    ``HTTPCORE``).
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            module = record.name.split(".")[0].upper()
            log = structlog.get_logger(module=module)
            level = record.levelname.lower()
            log_method = getattr(log, level, log.warning)
            log_method(record.getMessage(), stdlib_logger=record.name)
        except Exception:
            pass


def _module_level_filter(logger, method_name, event_dict):
    """Drop events below configured per-module level overrides."""
    if not _MODULE_OVERRIDES:
        return event_dict

    module = str(event_dict.get("module", ""))
    level_name = str(event_dict.get("level", "")).upper()
    event_level = logging._nameToLevel.get(level_name, logging.INFO)

    for prefix in sorted(_MODULE_OVERRIDES.keys(), key=len, reverse=True):
        if module == prefix or module.startswith(prefix + ".") or module.startswith(prefix):
            if event_level < _MODULE_OVERRIDES[prefix]:
                raise structlog.DropEvent()
            break
    return event_dict


def _emit_to_file_sinks(logger, method_name, event_dict):
    level_name = str(event_dict.get("level", "")).upper()
    event_level = logging._nameToLevel.get(level_name, logging.INFO)
    module = str(event_dict.get("module", ""))

    exc_info = None
    try:
        supplied = event_dict.get("exc_info")
        if supplied is True:
            exc_info = sys.exc_info()
        elif isinstance(supplied, tuple) and len(supplied) == 3:
            exc_info = supplied
        elif supplied and isinstance(supplied, BaseException):
            exc_info = (type(supplied), supplied, supplied.__traceback__)
        if exc_info is None:
            cur_exc = sys.exc_info()
            if cur_exc and cur_exc[0] is not None:
                exc_info = cur_exc
    except Exception:
        exc_info = None

    for min_level, handler, renderer, include_pfx, exclude_pfxs in list(_FILE_SINKS):
        if event_level < min_level:
            continue
        if include_pfx is not None and not module.startswith(include_pfx):
            continue
        if exclude_pfxs is not None and any(module.startswith(p) for p in exclude_pfxs):
            continue
        try:
            copy_for_file = dict(event_dict)
            rendered = renderer(None, method_name, copy_for_file)
            if event_level >= logging.ERROR and exc_info is not None:
                try:
                    tb_lines = traceback.format_exception(*exc_info)
                    tb_one_line = " | ".join(
                        line.strip() for line in tb_lines if line and line.strip()
                    )
                    if tb_one_line:
                        rendered = f"{rendered} exception={tb_one_line}"
                except Exception:
                    pass

            record = logging.LogRecord(
                name=module,
                level=event_level,
                pathname="",
                lineno=0,
                msg=rendered,
                args=(),
                exc_info=None,
            )
            handler.handle(record)
        except Exception:
            pass
    return event_dict


def _strip_exception_for_console(logger, method_name, event_dict):
    try:
        event_dict.pop("exc_info", None)
        event_dict.pop("exception", None)
        event_dict.pop("stack", None)
        event_dict.pop("stack_info", None)
    except Exception:
        pass
    return event_dict


# ---------------------------------------------------------------------------
# Logger — public API
# ---------------------------------------------------------------------------


class Logger:
    """Central logging facility for Hiro.

    Usage::

        Logger.set_level("DEBUG")        # 1. set level (idempotent)
        Logger.setup(console=True)       # 2. wire pipeline (one-time)
        Logger.open_log_dir(log_dir)     # 3. open file sinks (idempotent)

    ``Logger.get("MODULE")`` returns a lazy proxy and can be called at
    module level before any of the above — the proxy resolves on first
    actual log call, using whatever configuration is active at that point.
    """

    _level: int = logging.INFO
    _setup_done: bool = False

    # -- Level ---------------------------------------------------------------

    @classmethod
    def set_level(cls, level: str | int) -> None:
        """Set the global log level.  Idempotent; last call wins.

        Call *before* ``setup()`` for guaranteed correctness.  If called
        after ``setup()``, file sink thresholds are updated immediately.
        """
        cls._level = _resolve_level(level)
        if cls._setup_done:
            global _FILE_SINKS
            _FILE_SINKS = [
                (cls._level, handler, renderer, inc, exc)
                for (_, handler, renderer, inc, exc) in _FILE_SINKS
            ]
            for entry in _FILE_SINKS:
                entry[1].setLevel(cls._level)

    @classmethod
    def set_module_levels(cls, overrides: dict[str, str]) -> None:
        """Per-module level overrides (e.g. ``{"AGENT": "DEBUG"}``).

        Modules matching a prefix are held to the specified minimum level,
        independent of the global level.
        """
        for name, level_str in overrides.items():
            _MODULE_OVERRIDES[name] = _resolve_level(level_str)

    # -- Pipeline setup ------------------------------------------------------

    @classmethod
    def setup(cls, *, console: bool = True, json: bool = False) -> None:
        """One-time processor pipeline setup.

        Reads the current ``_level`` (set via ``set_level``).  Safe to call
        multiple times — second and subsequent calls are no-ops.
        """
        if cls._setup_done:
            return

        # The stdlib root logger stays at WARNING so third-party
        # DEBUG/INFO chatter is suppressed at the source.  A catch-all
        # bridge re-emits WARNING+ through structlog with proper
        # formatting and file-sink routing.  The default stdout handler
        # is removed — only our structlog pipeline writes to the console.
        logging.basicConfig(
            level=logging.WARNING,
            format="%(message)s",
            stream=sys.stdout,
            force=True,
        )
        root = logging.getLogger()
        for h in root.handlers[:]:
            root.removeHandler(h)
        root.addHandler(_StdlibCatchAll(level=logging.WARNING))

        def _add_module(logger, method_name, event_dict):
            if "module" not in event_dict and logger and getattr(logger, "name", None):
                event_dict["module"] = logger.name
            return event_dict

        processors = [
            structlog.processors.TimeStamper(fmt=None, utc=True, key="ts"),
            structlog.processors.add_log_level,
            _add_module,
            _module_level_filter,
            _emit_to_file_sinks,
            _strip_exception_for_console,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ]

        if not console:
            processors.append(_NullRenderer())
        elif json:
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(_ColourRenderer())

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(cls._level),
            context_class=dict,
            cache_logger_on_first_use=True,
        )
        cls._setup_done = True

    # -- Logger retrieval ----------------------------------------------------

    @classmethod
    def get(cls, name: str | None = None):
        """Return a structlog lazy proxy.

        Safe to call at module level before ``setup()``.  The proxy
        resolves on the first actual log call, using whatever configuration
        is active at that point.
        """
        if name is None:
            return structlog.get_logger()
        # Pass module as a keyword initial value — NOT .bind() — so the
        # proxy stays lazy until the first real log call.  .bind() eagerly
        # resolves the proxy, which would lock in the DEFAULT structlog
        # config when get() is called at module-import time (before setup).
        return structlog.get_logger(module=name)

    # -- File sinks ----------------------------------------------------------

    @classmethod
    def add_file_sink(
        cls,
        path: str,
        *,
        level: str | int | None = None,
        rotate: bool = True,
        mode: str = "a",
        max_bytes: int = LOG_ROTATION_MAX_BYTES,
        backup_count: int = LOG_ROTATION_BACKUP_COUNT,
        use_json: bool = False,
        use_csv: bool = False,
        include_prefix: str | None = None,
        exclude_prefix: str | tuple[str, ...] | None = None,
    ) -> logging.Handler:
        """Mirror log events into a file.

        *level* defaults to the global level set by ``set_level()``.
        Pass an explicit level only for sinks that should be MORE
        restrictive (e.g. an error-only file).
        """
        import os

        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        is_new_file = mode == "w" or not os.path.exists(path)

        min_level = _resolve_level(level) if level is not None else cls._level
        if rotate:
            handler: logging.Handler = logging.handlers.RotatingFileHandler(
                path,
                mode=mode,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        else:
            handler = logging.FileHandler(path, mode=mode, encoding="utf-8")

        handler.setLevel(min_level)
        handler.setFormatter(logging.Formatter("%(message)s"))

        if use_json:
            renderer = structlog.processors.JSONRenderer()
        elif use_csv:
            renderer = _CsvRenderer()
            if is_new_file:
                try:
                    with open(path, mode, encoding="utf-8") as fh:
                        fh.write(_CsvRenderer.HEADER + "\n")
                except OSError:
                    pass
        else:
            renderer = _PlainRenderer()

        if isinstance(exclude_prefix, str):
            exclude_prefix = (exclude_prefix,)

        _FILE_SINKS.append((min_level, handler, renderer, include_prefix, exclude_prefix))
        # File sink handlers are NOT attached to the stdlib root logger.
        # _emit_to_file_sinks calls handler.handle() directly from the
        # structlog pipeline, keeping third-party stdlib noise out of our
        # CSV log files.
        return handler

    @classmethod
    def remove_file_sink(cls, handler: logging.Handler):
        global _FILE_SINKS
        _FILE_SINKS = [entry for entry in _FILE_SINKS if entry[1] is not handler]

    _log_dir: Path | None = None

    @classmethod
    def open_log_dir(cls, log_dir: Path) -> None:
        """Open routed file sinks for a workspace log directory (idempotent).

        Creates two CSV sinks with module-prefix routing:
        - ``server.log``  — all events *except* ``CLI.*`` modules.
        - ``cli.log``     — only ``CLI.*`` modules.

        Both sinks inherit the global level from ``set_level()``.
        """
        log_dir = Path(log_dir)
        if cls._log_dir == log_dir:
            return
        log_dir.mkdir(parents=True, exist_ok=True)
        cls._log_dir = log_dir

        cls.add_file_sink(
            str(log_dir / "server.log"),
            use_csv=True,
            exclude_prefix=("CLI.",),
        )
        cls.add_file_sink(
            str(log_dir / "cli.log"),
            use_csv=True,
            include_prefix="CLI.",
        )

    # -- Stdlib bridging -----------------------------------------------------

    @classmethod
    def silence_stdlib(
        cls,
        logger_name: str,
        *,
        module: str,
        level: str | int = "WARNING",
    ) -> None:
        """Redirect a stdlib logger into the Hiro structured logger.

        Messages below *level* are suppressed.  Messages at or above
        *level* are re-emitted through ``Logger.get(module)`` so they
        appear in the console and file sinks with proper formatting.

        Propagation is disabled to prevent bare-text duplicates on the
        root logger.
        """
        numeric = _resolve_level(level)
        stdlib_logger = logging.getLogger(logger_name)
        stdlib_logger.setLevel(numeric)
        stdlib_logger.addHandler(_StdlibBridge(module, numeric))
        stdlib_logger.propagate = False

    # -- On/off --------------------------------------------------------------

    @classmethod
    def disable(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def enable(cls):
        logging.disable(logging.NOTSET)

    # -- Indentation helpers -------------------------------------------------

    @classmethod
    def set_indent_unit(cls, unit: str):
        global _INDENT_UNIT
        _INDENT_UNIT = unit

    @classmethod
    def push(cls, steps: int = 1):
        _INDENT_LEVEL.set(_INDENT_LEVEL.get() + steps)

    @classmethod
    def pop(cls, steps: int = 1):
        _INDENT_LEVEL.set(max(_INDENT_LEVEL.get() - steps, 0))

    @classmethod
    @contextmanager
    def indent(cls, steps: int = 1):
        token = _INDENT_LEVEL.set(_INDENT_LEVEL.get() + steps)
        try:
            yield
        finally:
            _INDENT_LEVEL.reset(token)


# ---------------------------------------------------------------------------
# Module-level convenience aliases
# ---------------------------------------------------------------------------

setup = Logger.setup
get_logger = Logger.get
set_level = Logger.set_level
set_module_levels = Logger.set_module_levels
disable = Logger.disable
enable = Logger.enable
