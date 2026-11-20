"""The core's logger: a thin layer over the logging foundation (hiro_commons.logging_foundation) that keeps the core's
own detail, field for field.

What it keeps:
- **FINEINFO** (15), between DEBUG and INFO, with `.fineinfo()` on every logger.
- **The message scope** (`log_scope`): device_id, msg_id, method, text_preview, traffic_class and traffic_subclass,
  stamped on every line logged inside it (across asyncio tasks too), as fields of the line.
- **The core's level and its level per area**: `set_level` (the workspace's `log_level`) for every core area, and
  `set_module_levels` (`module_log_levels`: `{"AGENT": "DEBUG", "COMM": "WARNING"}`) for the areas that start with a
  prefix, the longest prefix winning, above or below the core's level. Libraries stay at WARNING.
- **The colour console** of a foreground run (`[1:15:46] [INF] [COMM________] message key=value`).
- **Files of their own** for rows that aren't log lines (`add_file_sink`: the memory library's run ledger,
  `graph.log`): an area such a file takes never reaches the log.

What the foundation gives every core process (as every app): one JSON line per record with OpenTelemetry's field
names, its own daily file kept 30 days then archived, the queue that never blocks a caller, and every safety net.

Starting a process (once its folder is known):

    Logger.set_level(config.log_level)
    Logger.set_module_levels(config.module_log_levels)
    Logger.start(log_dir, name="server", service="core", console=foreground)

`name` names its files (`server-2026-11-20.jsonl`): `server` (the server), `cli` (each `hiro` command),
`channel-<name>` (a channel plugin), `gateway`. At start, the old CSV file of that name (`server.log` and its rotated
copies) moves into `archive/csv/` in the folder, as it is.

Code logs as it always has: `log = Logger.get("COMM")`, then `log.info("...", key=value)`; standard
`logging.getLogger(__name__)` lands in the same file. Tests that only need loggers call `Logger.setup(console=False)`:
the loggers work (into standard logging, which pytest captures), and no file is opened.
"""

from __future__ import annotations

import contextvars
import csv
import io
import logging
import logging.handlers
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Mapping

import structlog

from .constants.timing import LOG_ROTATION_BACKUP_COUNT, LOG_ROTATION_MAX_BYTES

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
    "get_logger",
    "log_scope",
    "CORE_PACKAGES",
    "ARCHIVE_CSV",
]

# The core's own packages whose modules log with standard logging (`logging.getLogger(__name__)`): they follow the
# core's level, as its structlog areas do. Every other standard logger (the libraries) stays at WARNING.
CORE_PACKAGES = (
    "hirocli", "hiroleague", "hirogateway", "hiro_commons", "hiro_memory", "hiro_channel_sdk", "hiro_channel_devices",
    "hiro_channel_whatsapp", "hiro_channel_echo", "hiro",
)
# The memory library's run ledger rows (its own CSV file, graph.log): never log lines, even with no ledger file open.
LEDGER_PREFIX = "AGENT.GRAPH.LEDGER"
ARCHIVE_CSV = Path("archive") / "csv"  # where the old CSV log files rest, in the logs folder

# ---------------------------------------------------------------------------
# Structured log scope — propagated automatically across asyncio tasks.
# Populated by log_scope(); injected into every event_dict by _inject_scope.
# ---------------------------------------------------------------------------
_DEVICE_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_device_id", default=None
)
_MSG_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_msg_id", default=None
)
_METHOD: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_method", default=None
)
_TEXT_PREVIEW_DEFAULT = object()
_TEXT_PREVIEW: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_text_preview", default=None
)
_TRAFFIC_CLASS: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_traffic_class", default=None
)
_TRAFFIC_SUBCLASS: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_traffic_subclass", default=None
)

_LEVELS: Mapping[str, int] = dict(logging._nameToLevel.items())

# Files of their own (the run ledger): (min_level, handler, renderer, include_prefix, exclude_prefixes). The
# foundation's structlog bridge reads it: an area a file opened for it alone takes is that file's row, not a log line.
_FILE_SINKS: list[tuple[int, logging.Handler, object, str | None, tuple[str, ...] | None]] = []
_MODULE_OVERRIDES: dict[str, int] = {}
_sink_log = logging.getLogger("hiro_commons.log")


def _resolve_level(level: str | int | None) -> int:
    if level is None:
        return logging.INFO
    if isinstance(level, int):
        return level
    return _LEVELS.get(str(level).upper(), logging.INFO)


def _inject_scope(logger, method_name, event_dict):
    """Stamp scope fields (device_id / msg_id / method / text_preview / traffic_class /
    traffic_subclass) from the active log_scope onto every event.

    If the call site already passed any of these keys as a structured-log kwarg, the
    explicit value is left unchanged — even when empty or None — so explicit
    suppression wins over contextvars. Only keys absent from ``event_dict`` receive
    non-empty values from the active :func:`log_scope`.
    """
    if "device_id" not in event_dict:
        d = _DEVICE_ID.get()
        if d:
            event_dict["device_id"] = d
    if "msg_id" not in event_dict:
        m = _MSG_ID.get()
        if m:
            event_dict["msg_id"] = m
    if "method" not in event_dict:
        mt = _METHOD.get()
        if mt:
            event_dict["method"] = mt
    if "text_preview" not in event_dict:
        tp = _TEXT_PREVIEW.get()
        if tp:
            event_dict["text_preview"] = tp
    if "traffic_class" not in event_dict:
        tcl = _TRAFFIC_CLASS.get()
        if tcl:
            event_dict["traffic_class"] = tcl
    if "traffic_subclass" not in event_dict:
        tsub = _TRAFFIC_SUBCLASS.get()
        if tsub:
            event_dict["traffic_subclass"] = tsub
    return event_dict


class _FlatCsvRenderer:
    """Render a flat structured event dict using a caller-supplied column order (a file of its own's rows)."""

    def __init__(self, columns: list[str]) -> None:
        self.columns = list(columns)
        buf = io.StringIO()
        csv.writer(buf).writerow(self.columns)
        self.header = buf.getvalue().rstrip("\r\n")

    def __call__(self, logger, method_name, event_dict):
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([event_dict.get(column, "") for column in self.columns])
        return buf.getvalue().rstrip("\r\n")


def _emit_to_file_sinks(logger, method_name, event_dict):
    """Write the event as a row of each file of its own that takes its area (the foundation's bridge runs this before
    it hands the event to standard logging)."""
    if not _FILE_SINKS:
        return event_dict
    level_name = str(event_dict.get("level", "")).upper()
    event_level = logging._nameToLevel.get(level_name, logging.INFO)
    module = str(event_dict.get("module", ""))
    for min_level, handler, renderer, include_pfx, exclude_pfxs in list(_FILE_SINKS):
        if event_level < min_level:
            continue
        if include_pfx is not None and not module.startswith(include_pfx):
            continue
        if exclude_pfxs is not None and any(module.startswith(p) for p in exclude_pfxs):
            continue
        try:
            rendered = renderer(None, method_name, dict(event_dict))
            handler.handle(logging.LogRecord(name=module, level=event_level, pathname="", lineno=0, msg=rendered,
                                             args=(), exc_info=None))
        except Exception:
            # A row that couldn't be written: said in the log (a standard logger, so it can't loop back here)
            _sink_log.warning("A row for %s couldn't be written to its file", module, exc_info=True)
    return event_dict


def _enabled(module: str, level: int) -> bool:
    """The core's rule for its structlog areas: the area's own level when a prefix names it (the longest prefix
    wins), else the core's level. The run ledger's rows are never log lines."""
    if module.startswith(LEDGER_PREFIX):
        return False
    for prefix in sorted(_MODULE_OVERRIDES, key=len, reverse=True):
        if module.startswith(prefix):
            return level >= _MODULE_OVERRIDES[prefix]
    return level >= Logger._level


_LEVEL_ABBREV = {"DEBUG": "DBG", "FINEINFO": "FNI", "INFO": "INF", "WARNING": "WRN", "ERROR": "ERR", "CRITICAL": "CRT"}


class _ColourFormat(logging.Formatter):
    """The core's console line, as it always looked: `[time] [LVL] [MODULE______] message key=value`, coloured (a
    foreground run; the file keeps the whole record, the console a short line, without its traceback)."""

    def __init__(self) -> None:
        super().__init__()
        import colorama

        colorama.just_fix_windows_console()
        f, s = colorama.Fore, colorama.Style
        self._dim, self._reset = s.DIM, s.RESET_ALL
        self._levels = {"DEBUG": f.BLUE, "FINEINFO": f.CYAN, "INFO": f.GREEN, "WARNING": f.YELLOW, "ERROR": f.RED,
                        "CRITICAL": f.MAGENTA}
        self._palette = [f.CYAN, f.MAGENTA, f.YELLOW, f.GREEN]
        self._white = f.WHITE

    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        level = record.levelname.upper()
        module = record.name
        shown = module[:12] if len(module) > 12 else module.ljust(12, "_")
        colour = self._palette[sum(ord(c) for c in module) % len(self._palette)] if module else self._white
        fields = getattr(record, "hiro_fields", None) or {}
        kv = " ".join(f"{k}={v}" for k, v in fields.items() if not k.startswith(("exception.", "code.")))
        parts = [f"{self._dim}[{ts}]", f"{self._levels.get(level, self._white)}[{_LEVEL_ABBREV.get(level, level[:3])}]",
                 f"{colour}[{shown}]", self._reset + record.getMessage()]
        if kv:
            parts.append(self._dim + " " + kv)
        parts.append(self._reset)
        return " ".join(parts)


def archive_csv(folder: Path, name: str) -> list[Path]:
    """Move the old CSV log file `name.log` (and its rotated copies `name.log.1`...) into `archive/csv/`, as they are.
    Once per file: a name already there gets the time it moved added to it. The files moved."""
    folder = Path(folder)
    moved = []
    for path in sorted(folder.glob(f"{name}.log*")):
        tail = path.name[len(name):]
        if not path.is_file() or not (tail == ".log" or (tail.startswith(".log.") and tail[5:].isdigit())):
            continue
        target = folder / ARCHIVE_CSV / path.name
        if target.exists():
            target = target.with_name(f"{path.name}.{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
            moved.append(target)
        except OSError as exc:
            # Another process still writes it (an old one on Windows): the next start moves it.
            _sink_log.warning("Logs: the old %s stays where it is for now (%s)", path.name, exc)
    return moved


# ---------------------------------------------------------------------------
# Logger — public API
# ---------------------------------------------------------------------------


class Logger:
    """The core's logging, over the foundation.

    Usage::

        Logger.set_level("DEBUG")                         # 1. the core's level (idempotent)
        Logger.set_module_levels({"COMM": "WARNING"})     # 2. levels per area (optional)
        Logger.start(log_dir, name="server", service="core", console=True)   # 3. the file, the nets

    ``Logger.get("MODULE")`` returns a lazy proxy and can be called at module level before any of the above.
    """

    _level: int = logging.INFO
    _setup_done: bool = False
    _console: bool = False
    _started: tuple[Path, str] | None = None

    # -- Level ---------------------------------------------------------------

    @classmethod
    def set_level(cls, level: str | int) -> None:
        """The core's level, for every core area without one of its own. Idempotent; last call wins, at once."""
        cls._level = _resolve_level(level)
        if cls._started is not None:
            for package in CORE_PACKAGES:
                logging.getLogger(package).setLevel(cls._level)

    @classmethod
    def set_module_levels(cls, overrides: dict[str, str]) -> None:
        """Levels per area (e.g. ``{"AGENT": "DEBUG"}``): an area that starts with a prefix follows the prefix's level
        (the longest prefix wins), above or below the core's level."""
        for name, level_str in overrides.items():
            _MODULE_OVERRIDES[name] = _resolve_level(level_str)

    # -- Setup ---------------------------------------------------------------

    @classmethod
    def setup(cls, *, console: bool = True) -> None:
        """Wire the core's loggers into standard logging, with the core's rule for its areas; no file yet (tests, and
        a process before its folder is known). ``start()`` does this too."""
        from .logging_foundation import bridge

        cls._console = console
        bridge.decide_with(_enabled)
        bridge.wire()
        cls._setup_done = True

    @classmethod
    def start(cls, folder: Path, *, name: str, service: str, console: bool | None = None) -> Path:
        """This process's logging on the foundation: its own daily file in `folder` (`<name>-<day>.jsonl`), the
        safety nets, the core's levels and its colour console (`console`: the setup()'s choice when not given). The
        old CSV file of that name moves into `archive/csv/` first. Again with the same folder and name: nothing
        changes. The file of today."""
        from . import logging_foundation

        folder = Path(folder)
        if console is None:
            console = cls._console
        if cls._started == (folder, name):
            return folder / logging_foundation.daily.file_name(name, _today())
        moved = archive_csv(folder, name)
        level = logging.getLevelName(cls._level)
        levels = {"": "WARNING", **{package: level for package in CORE_PACKAGES}}
        today = logging_foundation.setup(folder, name=name, service=service, levels=levels, console=console,
                                         console_format=_ColourFormat() if console else None)
        cls.setup(console=console)
        cls._started = (folder, name)
        if moved:
            _sink_log.info("Logs: the old CSV files moved to %s", folder / ARCHIVE_CSV,
                           extra={"files": [p.name for p in moved]})
        return today

    @classmethod
    def close(cls) -> None:
        """Write what is queued and close the file (tests; the foundation does it at exit by itself)."""
        from . import logging_foundation

        logging_foundation.close()
        cls._started = None

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

    # -- Files of their own --------------------------------------------------

    @classmethod
    def add_file_sink(
        cls,
        path: str,
        *,
        csv_columns: list[str] | tuple[str, ...],
        level: str | int | None = None,
        max_bytes: int = LOG_ROTATION_MAX_BYTES,
        backup_count: int = LOG_ROTATION_BACKUP_COUNT,
        include_prefix: str | None = None,
        exclude_prefix: str | tuple[str, ...] | None = None,
    ) -> logging.Handler:
        """A CSV file of its own for rows that aren't log lines (the run ledger), with these columns, rotated by size.
        Opened for an area alone (`include_prefix`), that area's events are its rows and never log lines."""
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        min_level = _resolve_level(level) if level is not None else cls._level
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            path, mode="a", maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        handler.setLevel(min_level)
        handler.setFormatter(logging.Formatter("%(message)s"))
        renderer = _FlatCsvRenderer(list(csv_columns))
        _write_header(Path(path), renderer)
        if isinstance(exclude_prefix, str):
            exclude_prefix = (exclude_prefix,)
        _FILE_SINKS.append((min_level, handler, renderer, include_prefix, exclude_prefix))
        return handler

    @classmethod
    def remove_file_sink(cls, handler: logging.Handler):
        global _FILE_SINKS
        _FILE_SINKS = [entry for entry in _FILE_SINKS if entry[1] is not handler]


def _write_header(path: Path, renderer: _FlatCsvRenderer) -> None:
    """A new file gets the header; a file whose header is a shorter run of the same columns (a column added since) gets
    the new header, its rows kept."""
    try:
        if not path.exists() or path.stat().st_size == 0:
            path.write_text(renderer.header + "\n", encoding="utf-8")
            return
        with path.open(encoding="utf-8") as fh:
            lines = fh.readlines()
        old_columns = next(csv.reader([lines[0].rstrip("\r\n")]))
        if old_columns != renderer.columns and old_columns == renderer.columns[: len(old_columns)]:
            lines[0] = renderer.header + "\n"
            with path.open("w", encoding="utf-8") as fh:
                fh.writelines(lines)
    except OSError as exc:
        _sink_log.warning("The header of %s couldn't be written (%s)", path.name, exc)


def _today():
    """The house's day (the daily files are named by it)."""
    from datetime import datetime

    return datetime.now().astimezone().date()


# ---------------------------------------------------------------------------
# Module-level convenience aliases
# ---------------------------------------------------------------------------

get_logger = Logger.get


@contextmanager
def log_scope(
    *,
    device_id: str | None = None,
    msg_id: str | None = None,
    method: str | None = None,
    text_preview: str | None | object = _TEXT_PREVIEW_DEFAULT,
    traffic_class: str | None = None,
    traffic_subclass: str | None = None,
):
    """Open a structured logging scope for one device / message / request.

    Every log line emitted within this context — including inside asyncio tasks
    spawned from it — is automatically stamped with the supplied fields (the line's
    fields).  Explicit values passed at call sites always win over the
    scope (the processor only injects when the key is absent).

    Fields:
        device_id  — the UUID of the device this activity is about.
        msg_id     — routing.id of the user message driving this activity
                     (set only for message-type messages and ref_id-bearing events).
        method     — JSON-RPC method name for request/response flows
                     (e.g. ``"channels.list"``, ``"policy.get"``).
        text_preview — short human-readable message snippet for log UIs / cross-row anchoring.
        traffic_class — Tier-1 operational classification (e.g. ``"inbound.message"``,
                     ``"outbound.response"``, ``"infra.event"``); see
                     ``hiro_channel_sdk.log_scope_fields.TRAFFIC_CLASSES``.
        traffic_subclass — Tier-2 detail under ``traffic_class``: method name,
                     content shape, or event type.

    ``text_preview`` is optional: omit the keyword entirely to inherit the parent's
    value; pass ``None`` or ``''`` explicitly to bind an empty preview for this nest.

    Scopes nest safely; inner scopes shadow outer ones and restore on exit.
    """
    tokens: list[tuple] = []
    try:
        if device_id is not None:
            tokens.append((_DEVICE_ID, _DEVICE_ID.set(device_id)))
        if msg_id is not None:
            tokens.append((_MSG_ID, _MSG_ID.set(msg_id)))
        if method is not None:
            tokens.append((_METHOD, _METHOD.set(method)))
        if text_preview is not _TEXT_PREVIEW_DEFAULT:
            tokens.append(
                (
                    _TEXT_PREVIEW,
                    _TEXT_PREVIEW.set((text_preview or "").strip() or None),
                )
            )
        if traffic_class is not None:
            tokens.append((_TRAFFIC_CLASS, _TRAFFIC_CLASS.set(traffic_class)))
        if traffic_subclass is not None:
            tokens.append((_TRAFFIC_SUBCLASS, _TRAFFIC_SUBCLASS.set(traffic_subclass)))
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)

