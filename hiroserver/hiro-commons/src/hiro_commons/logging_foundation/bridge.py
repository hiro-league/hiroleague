"""structlog's lines into standard Python logging, so they reach the process's own file.

The SDK (the app-to-core link: `EXTENSION`, `CH_TRANSPORT`) and the memory library log through hiro_commons' `Logger`,
which is structlog. The core wires structlog to its own CSV files (`Logger.setup()`); a process on the foundation
wires it here instead: each event becomes a standard logging record of the logger named by its area, its fields
become the line's Attributes, and its exception stays an exception. Standard logging is the front door; this is the
side door for code written for structlog.

- The `Logger`'s file sinks still get their events first (the memory library's run ledger, `graph.log`: a sink of its
  own). An event that a sink of its own takes (one opened for its area alone, `include_prefix`) is that file's row,
  not a log line, so it goes no further.
- The core's scope fields (device, message id, method, text preview, traffic class and subclass) ride along as
  fields, as in the core's files.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.typing import EventDict

from .. import log as commons_log
from .line import ATTRIBUTES

_NOT_FIELDS = {"event", "level", "module", "ts", "exc_info", "exception", "stack_info", "stack"}
_saved: dict[str, Any] | None = None  # structlog's configuration before ours, put back by unwire()


def _add_module(logger: Any, _method: str, event: EventDict) -> EventDict:
    if "module" not in event and getattr(logger, "name", None):
        event["module"] = logger.name
    return event


def _own_file_takes(module: str) -> bool:
    """A file sink opened for this area alone (the run ledger's) takes its events as rows of that file."""
    return any(include is not None and module.startswith(include) for _lvl, _h, _r, include, _ex in commons_log._FILE_SINKS)


def _level(method: str, event: EventDict) -> int:
    name = str(event.get("level") or method or "info").upper()
    if name in ("EXCEPTION", "MSG"):
        return logging.ERROR if name == "EXCEPTION" else logging.INFO
    found = logging.getLevelName(name)
    return found if isinstance(found, int) else logging.INFO


def _exc_info(event: EventDict) -> Any:
    supplied = event.get("exc_info")
    if supplied is True:
        info = sys.exc_info()
        return info if info[0] is not None else None
    if isinstance(supplied, BaseException):
        return type(supplied), supplied, supplied.__traceback__
    if isinstance(supplied, tuple) and len(supplied) == 3:
        return supplied
    return None


def to_stdlib(_logger: Any, method: str, event: EventDict) -> EventDict:
    """The last step: hand the event to standard logging, then stop structlog's own output."""
    module = str(event.get("module") or "structlog")
    if not _own_file_takes(module):
        level = _level(method, event)
        logger = logging.getLogger(module)
        if logger.isEnabledFor(level):
            fields = {k: v for k, v in event.items() if k not in _NOT_FIELDS}
            logger.log(level, "%s", event.get("event", ""), exc_info=_exc_info(event), extra={ATTRIBUTES: fields},
                       stack_info=bool(event.get("stack_info")))
    raise structlog.DropEvent


def wire() -> None:
    """Send every structlog event of this process through `to_stdlib` (again: changes nothing)."""
    global _saved
    if _saved is None:
        _saved = structlog.get_config()
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt=None, utc=True, key="ts"),  # the file sinks' rows want it
            structlog.processors.add_log_level,
            _add_module,
            commons_log._inject_scope,
            commons_log._emit_to_file_sinks,
            to_stdlib,
        ],
        # Every level passes here; each area's standard logger decides (isEnabledFor above). FINEINFO's methods exist
        # on it because hiro_commons.log registers the level when it loads.
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        cache_logger_on_first_use=False,  # unwire() must reach loggers made before it
    )


def unwire() -> None:
    """Put structlog back as it was before wire() (tests share a process with code that set it up its own way)."""
    global _saved
    if _saved is not None:
        structlog.configure(**_saved)
        _saved = None
