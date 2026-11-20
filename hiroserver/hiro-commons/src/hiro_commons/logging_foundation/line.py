"""What a log line holds: one JSON object per line, with OpenTelemetry's log field names.

    {"Timestamp": "2026-11-19T21:15:03.123456Z", "SeverityText": "WARNING", "SeverityNumber": 13,
     "Body": "HA connection lost (timeout); retrying in 5 s", "InstrumentationScope": "homehiro.ha",
     "Attributes": {"elapsed_ms": 5003, "exception.type": "TimeoutError", ...},
     "Resource": {"service.name": "home"}}

- `Timestamp`: when it happened, in UTC (ISO 8601; OpenTelemetry's own wire form is nanoseconds since 1970).
- `SeverityText`, `SeverityNumber`: the level as the code named it (DEBUG, FINEINFO, INFO, WARNING, ERROR, CRITICAL),
  and OpenTelemetry's number for it (DEBUG 5, FINEINFO 8, INFO 9, WARN 13, ERROR 17, FATAL 21).
- `Body`: the sentence for a person.
- `InstrumentationScope`: the area: the logger's name (`homehiro.ha`, `EXTENSION`). Each area can have its own level.
- `Attributes`: the line's fields, readable ones first as the code gave them; an exception's `exception.type`,
  `exception.message` and `exception.stacktrace` (OpenTelemetry's names) last.
- `Resource`: the process that wrote it (`service.name`: `home`, `net`, the core...).
- `TraceId`, `SpanId`: the story and its step, once a story carries an id (the plan's phases 3 and 4); absent until
  then.

Only the Stable parts of OpenTelemetry are used: its log data model's field names and severity numbers. No
OpenTelemetry package is needed for that.

A field whose name says it holds a secret (a password, a token, a key, a cookie) is written as "[hidden]": no secret
in a line, even when a caller passes one by mistake.
"""

from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# The attributes every LogRecord has; anything else on a record came from `extra=` and is one of the line's fields.
_RECORD_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}
ATTRIBUTES = "attributes"  # a record's dict of fields (the structlog bridge puts them here, as `extra={...}` could)
# Set by the foundation itself, or a copy of the sentence for a colour console (uvicorn's): not fields.
_OURS = frozenset({ATTRIBUTES, "hiro_line", "hiro_fields", "color_message"})

_SECRET_NAMES = frozenset({"password", "passwd", "token", "secret", "api_key", "apikey", "authorization", "cookie",
                           "access_token", "refresh_token", "session_token", "private_key"})
_SECRET_ENDS = ("_password", "_token", "_secret", "_key", "_cookie")
HIDDEN = "[hidden]"


def severity_number(level: int) -> int:
    """OpenTelemetry's SeverityNumber for a Python level (its own mapping: 10 → DEBUG 5, 20 → INFO 9...)."""
    if level >= logging.CRITICAL:
        return 21
    if level >= logging.ERROR:
        return 17
    if level >= logging.WARNING:
        return 13
    if level >= logging.INFO:
        return 9
    if level > logging.DEBUG:  # FINEINFO (15), between DEBUG and INFO: DEBUG4, the highest debug number
        return 8
    if level >= logging.DEBUG:
        return 5
    return 1  # TRACE


def is_secret(name: str) -> bool:
    low = name.lower()
    return low in _SECRET_NAMES or low.endswith(_SECRET_ENDS)


def _value(v: Any) -> Any:
    """A field's value as JSON can hold it: numbers, text, true/false and null as they are, lists and dicts as they
    are when they hold those, anything else as its text."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): (HIDDEN if is_secret(str(k)) else _value(x)) for k, x in v.items()}
    return str(v)


def fields_of(record: logging.LogRecord) -> dict[str, Any]:
    """The record's own fields: those the bridge or `extra=` put on it, secrets hidden."""
    found: dict[str, Any] = {}
    given = getattr(record, ATTRIBUTES, None)
    if isinstance(given, dict):
        found.update(given)
    for key, v in record.__dict__.items():
        if key not in _RECORD_KEYS and key not in _OURS and not key.startswith("_"):
            found[key] = v
    return {k: (HIDDEN if is_secret(k) else _value(v)) for k, v in found.items()}


def body_of(record: logging.LogRecord) -> str:
    try:
        return record.getMessage()
    except (TypeError, ValueError, KeyError):  # a call whose arguments don't fit its message: keep both rather than lose the line
        return f"{record.msg} {record.args!r}"


def build(record: logging.LogRecord, service: str) -> dict[str, Any]:
    """The line for a record, as a dict in the order it is written."""
    attributes = fields_of(record)
    if record.exc_info and record.exc_info[1] is not None:
        kind, exc, tb = record.exc_info
        attributes["exception.type"] = f"{kind.__module__}.{kind.__qualname__}" if kind and kind.__module__ != "builtins" \
            else (kind.__qualname__ if kind else "")
        attributes["exception.message"] = str(exc)
        attributes["exception.stacktrace"] = "".join(traceback.format_exception(kind, exc, tb)).rstrip()
    elif record.exc_text:
        attributes["exception.stacktrace"] = record.exc_text
    if record.stack_info:
        attributes["code.stacktrace"] = record.stack_info
    line: dict[str, Any] = {
        "Timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "SeverityText": record.levelname,
        "SeverityNumber": severity_number(record.levelno),
        "Body": body_of(record),
        "InstrumentationScope": record.name,
    }
    if attributes:
        line["Attributes"] = attributes
    line["Resource"] = {"service.name": service}
    return line


def render(line: dict[str, Any]) -> str:
    """One line of the file: JSON, never more than one line (a newline in a message is written as \\n)."""
    return json.dumps(line, ensure_ascii=False, default=str, separators=(",", ":"))


# --- reading ------------------------------------------------------------------------------------------------------


@dataclass
class Line:
    """A line read back from a file."""

    at: datetime  # aware, in UTC
    level: str  # SeverityText
    number: int  # SeverityNumber
    body: str
    scope: str
    attributes: dict[str, Any] = field(default_factory=dict)
    service: str = ""
    trace_id: str | None = None
    span_id: str | None = None

    @property
    def stacktrace(self) -> str | None:
        st = self.attributes.get("exception.stacktrace") or self.attributes.get("code.stacktrace")
        return str(st) if st else None

    @property
    def fields(self) -> dict[str, Any]:
        """The fields a person reads: everything but the exception's own (shown as its traceback)."""
        return {k: v for k, v in self.attributes.items() if not k.startswith("exception.") and k != "code.stacktrace"}


def parse(text: str) -> Line | None:
    """A line of a file, or None when it isn't one (a half-written line, something else)."""
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            return None
        at = datetime.fromisoformat(str(raw["Timestamp"]).replace("Z", "+00:00"))
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        attributes = raw.get("Attributes") or {}
        resource = raw.get("Resource") or {}
        return Line(at=at, level=str(raw.get("SeverityText") or "INFO"), number=int(raw.get("SeverityNumber") or 9),
                    body=str(raw.get("Body") or ""), scope=str(raw.get("InstrumentationScope") or ""),
                    attributes=attributes if isinstance(attributes, dict) else {},
                    service=str(resource.get("service.name") or "") if isinstance(resource, dict) else "",
                    trace_id=raw.get("TraceId"), span_id=raw.get("SpanId"))
    except (ValueError, KeyError, TypeError):
        return None
