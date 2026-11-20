"""Log reading tools: search and tail the server, channel, gateway and CLI log files.

These tools read the core's daily log files, written through the logging foundation (hiro_commons.log:
`Logger.start`): one JSON line per record with OpenTelemetry's field names, one file a day, kept 30 days.
They are available to the AI agent (for natural-language log queries), the CLI (`hiro logs search/tail`), and the
admin UI (direct import).

The files, in the workspace's logs folder (and the gateway's):
- `server-<YYYY-MM-DD>.jsonl`: the server process;
- `cli-<YYYY-MM-DD>.jsonl`: every `hiro` command;
- `channel-<name>-<YYYY-MM-DD>.jsonl`: each channel plugin;
- `gateway-<YYYY-MM-DD>.jsonl`, and the gateway instance's `stderr.log` (a crash before its logging started);
- the log store's streams (services/log_store.py): the lines every other part sends the core, `app-<name>-<day>.jsonl`
  for each app (`app-home`, `app-net`...), and any other stream a part writes (the device app's `device`).

Sources: `all` (every stream: the core's and every app's), `core` (the core's own: server, CLI, channels, gateway; the
admin Logs page reads these), `server`, `cli`, `channels`, `gateway`, `apps` (every app's), or one stream by its name
(`app-home`, or the app's own name, `home`; `device`).

Two questions answer across every part at once: `log_problems` (what went wrong in a span of time) and `log_story`
(everything one story did, by its id). Their rows are brief, for an agent to read: the time in words, the source, the
level, the area, the message, the fields and the story id.

A row keeps the shape the admin Logs page has always read (time, level, module, message, extra, the scope fields...).
Its source is the file's, except that the server's and the CLI's are told apart by module, as they always were: a
`CLI.*` module is `cli`, any other `server`.
"""

from __future__ import annotations

import ast
import datetime
import html as _html
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger
from hiro_commons.logging_foundation import daily, story
from hiro_commons.timestamps import human_datetime
from hiro_commons.logging_foundation.line import Line, parse

from .base import Tool, ToolParam

log = Logger.get("LOG_TOOLS")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LEVEL_ORDER: dict[str, int] = {
    "DEBUG": 0,
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}
_DEFAULT_TAIL_LINES = 500
_DEFAULT_SEARCH_LIMIT = 200
# How many bytes to read from near the end of a file for tail operations, to start with (doubled until enough lines).
_TAIL_READ_BYTES = 262_144
# A search reads each source's newest files until this many bytes (at least one file): about the old single file's.
_SEARCH_BYTES = 24 * 1024 * 1024
# Expand a time-range read until the oldest row is before *min_ts*, the files run out, or this many rows.
_TAIL_SINCE_MAX_LINES = 300_000
_STARTUP_MESSAGE = "🚀 Hiro Server starting"
_SOURCE_HELP = (
    "Log source: 'all' (the core and every app, the default), 'core' (server, channels, gateway, CLI), 'server', "
    "'channels', 'gateway', 'cli', 'apps' (every app), or one app by its name ('home', 'net') or stream ('app-home')"
)


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------


def _resolve_log_dir(workspace: str | None) -> Path:
    """Return the effective log directory for the given (or default) workspace."""
    from ..domain.config import load_config, resolve_log_dir
    from ..domain.workspace import resolve_workspace

    entry, _ = resolve_workspace(workspace)
    ws_path = Path(entry.path)
    config = load_config(ws_path)
    return resolve_log_dir(ws_path, config)


def _resolve_gateway_instance_path() -> Path | None:
    """Return the default gateway instance path, or None."""
    try:
        from hirogateway.instance import load_registry

        registry = load_registry()
        if not registry.instances:
            return None
        name = registry.default_instance or next(iter(registry.instances))
        entry = registry.instances.get(name)
        if entry is None:
            return None
        return Path(entry.path)
    except Exception as exc:
        log.warning("Failed to resolve gateway instance path", error=str(exc))
        return None


def _resolve_gateway_log_dir() -> Path | None:
    """Return the log directory for the default gateway instance, or None."""
    try:
        from hirogateway.config import load_config as gw_load_config
        from hirogateway.config import resolve_log_dir as gw_resolve_log_dir

        instance_path = _resolve_gateway_instance_path()
        if instance_path is None:
            return None
        config = gw_load_config(instance_path)
        return gw_resolve_log_dir(instance_path, config)
    except Exception as exc:
        log.warning("Failed to resolve gateway log dir", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# The streams: a source's daily files (or a plain stderr file)
# ---------------------------------------------------------------------------

_CHANNEL_FILE = re.compile(r"^channel-(?P<channel>.+)-\d{4}-\d{2}-\d{2}\.jsonl$")


@dataclass(frozen=True)
class LogStream:
    """One source's files: the daily files of `name` in `folder`, or one plain stderr file (`plain`)."""

    label: str  # "server", "cli", "channel-whatsapp", "gateway"
    folder: Path
    name: str | None = None
    plain: Path | None = None

    def files(self) -> list[tuple[datetime.date | None, Path]]:
        """Its files, newest first (a plain file has no day)."""
        if self.plain is not None:
            return [(None, self.plain)] if _file_has_content(self.plain) else []
        assert self.name is not None
        return daily.files(self.folder, self.name)

    def recent(self) -> list[Path]:
        """The files a live tail follows: today's and yesterday's (a line written just before midnight)."""
        if self.plain is not None:
            return [p for _d, p in self.files()]
        yesterday = _today() - datetime.timedelta(days=1)
        return [p for d, p in self.files() if d is not None and d >= yesterday]


def _today() -> datetime.date:
    return datetime.datetime.now().astimezone().date()  # the house's day: the files are named by it


def channel_names(log_dir: Path) -> list[str]:
    """The channels with a daily file in the folder (within the 30 days kept)."""
    names = set()
    if log_dir.is_dir():
        for path in log_dir.glob("channel-*.jsonl"):
            m = _CHANNEL_FILE.match(path.name)
            if m:
                names.add(m["channel"])
    return sorted(names)


_DAILY_FILE = re.compile(r"^(?P<name>.+)-\d{4}-\d{2}-\d{2}\.jsonl$")
_CORE_STREAMS = ("server", "cli", "gateway")  # (the gateway's folder may be the core's)
_APP_PREFIX = "app-"


def stream_names(log_dir: Path) -> list[str]:
    """Every stream with a daily file in the folder: the core's own and the log store's (each app's, the device's)."""
    names = set()
    if log_dir.is_dir():
        for path in log_dir.glob("*.jsonl"):
            m = _DAILY_FILE.match(path.name)
            if m:
                names.add(m["name"])
    return sorted(names)


def _is_core_stream(name: str) -> bool:
    return name in _CORE_STREAMS or name.startswith("channel-")


def has_files(folder: Path | None, name: str) -> bool:
    return folder is not None and bool(daily.files(folder, name))


def _collect_log_files(
    log_dir: Path,
    gateway_log_dir: Path | None,
    source: str,
) -> list[LogStream]:
    """The streams for the requested source(s)."""
    streams: list[LogStream] = []
    src = (source or "all").strip().lower()
    core = src in ("all", "core")

    # The server's and the CLI's files are read together: each row's source comes from its module (see _source_of).
    if core or src in ("server", "cli"):
        streams.append(LogStream("server", log_dir, "server"))
        streams.append(LogStream("cli", log_dir, "cli"))

    if core or src == "channels":
        for channel in channel_names(log_dir):
            streams.append(LogStream(f"channel-{channel}", log_dir, f"channel-{channel}"))

    # The log store's streams: what the apps (and the device app) sent the core
    others = [n for n in stream_names(log_dir) if not _is_core_stream(n)]
    if src == "all":
        wanted = others
    elif src == "apps":
        wanted = [n for n in others if n.startswith(_APP_PREFIX)]
    elif src in others:
        wanted = [src]
    elif f"{_APP_PREFIX}{src}" in others:  # an app by its own name: "home"
        wanted = [f"{_APP_PREFIX}{src}"]
    else:
        wanted = []
    streams.extend(LogStream(name, log_dir, name) for name in wanted)

    if (core or src == "gateway") and gateway_log_dir is not None:
        streams.append(LogStream("gateway", gateway_log_dir, "gateway"))

    if core or src == "gateway":
        gateway_instance_path = _resolve_gateway_instance_path()
        if gateway_instance_path is not None:
            stderr_file = gateway_instance_path / "stderr.log"
            if _file_has_content(stderr_file):
                streams.append(LogStream("gateway", gateway_instance_path, plain=stderr_file))

    return streams


def _keep_source(rows: list[dict[str, Any]], source: str | None) -> list[dict[str, Any]]:
    """The server's and the CLI's rows share files: keep only the asked one's."""
    src = (source or "all").lower()
    if src in ("server", "cli"):
        return [r for r in rows if r.get("source") == src]
    return rows


def _file_has_content(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Rows: one line, in the shape the admin page reads
# ---------------------------------------------------------------------------

_LEVEL_CSS_CLASS = {
    "DEBUG": "log-lvl-debug",
    "FINEINFO": "log-lvl-fineinfo",
    "INFO": "log-lvl-info",
    "WARNING": "log-lvl-warning",
    "ERROR": "log-lvl-error",
    "CRITICAL": "log-lvl-critical",
}


def _module_color_idx(module: str) -> int:
    """Stable 0-3 colour bucket for a module name (same hash as terminal renderer)."""
    return sum(ord(c) for c in module) % 4


# Space-separated "key=value" pairs in a row's extra. Split on spaces that start a new "word=" token so values may
# contain spaces. (A row read from a file carries its fields as pairs too: `fields`, which nothing has to split.)
_EXTRA_PAIR_BOUNDARY = re.compile(r" (?=[\w][\w.]*=)")


def _split_extra_segments(extra: str) -> list[str]:
    s = (extra or "").strip()
    if not s:
        return []
    return _EXTRA_PAIR_BOUNDARY.split(s)


def _segment_to_key_value(seg: str) -> tuple[str, str]:
    if "=" not in seg:
        return ("", seg)
    k, _, v = seg.partition("=")
    return (k, v)


def pretty_print_log_value(value: str) -> tuple[bool, str]:
    """Try to format a log field as indented JSON for the admin detail panel.

    A field that holds a list or a dict is written as JSON; older text may hold Python's ``repr`` (single quotes,
    ``True``/``None``), which :func:`ast.literal_eval` reads, then :func:`json.dumps` shows.
    """
    raw = (value or "").strip()
    if not raw:
        return (False, value)
    try:
        obj = json.loads(raw)
        return (True, json.dumps(obj, indent=2, ensure_ascii=False))
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        obj = ast.literal_eval(raw)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return (False, value)
    if isinstance(obj, (dict, list, tuple)):
        return (True, json.dumps(obj, indent=2, ensure_ascii=False))
    return (False, value)


def _pairs_html(pairs: list[tuple[str, str]], *, rows: bool) -> str:
    """Coloured key=value spans: one line (the table cell) or one row each (the tooltip)."""
    parts: list[str] = []
    for k, v in pairs:
        inner = (
            f'<span class="log-extra-key">{_html.escape(k)}</span>'
            f'<span class="log-extra-eq">=</span>'
            f'<span class="log-extra-val">{_html.escape(v)}</span>'
            if k
            else f'<span class="log-extra-val">{_html.escape(v)}</span>'
        )
        parts.append(f'<div class="log-extra-tooltip-row">{inner}</div>' if rows else inner)
    return ("" if rows else " ").join(parts)


def _epoch_to_dt(ts: float | str) -> datetime.datetime | None:
    """An epoch timestamp as the house's local time, or None."""
    try:
        return datetime.datetime.fromtimestamp(float(ts)).astimezone()
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def _format_date(ts: float | str) -> str:
    """Format an epoch as 'Mar 18'. Returns '' if not parseable."""
    dt = _epoch_to_dt(ts)
    if dt is None:
        return ""
    # %#d on Windows, %-d on Unix — use manual formatting to stay portable.
    return f"{dt.strftime('%b')} {dt.day}"


def _to_12h(ts: float | str) -> str:
    """Format an epoch as 'H:MM:SS AM/PM'. Returns it unchanged if not parseable."""
    dt = _epoch_to_dt(ts)
    if dt is None:
        return str(ts)
    hour = dt.hour
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{dt.minute:02d}:{dt.second:02d} {suffix}"


# Keys stamped by hiro_commons.log.log_scope that identify a device or message.
_SCOPE_KEYS = frozenset(
    {"device_id", "msg_id", "method", "text_preview", "traffic_class", "traffic_subclass"}
)


def _field_text(value: Any) -> str:
    """A field's value as the page shows it: lists and dicts as JSON, anything else as its text."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _pairs_of(line: Line) -> list[tuple[str, str]]:
    """The line's fields as (key, text) pairs, in order; its traceback last, as `exception` (or `stack`)."""
    pairs = [(k, _field_text(v)) for k, v in line.fields.items()]
    if line.attributes.get("exception.stacktrace"):
        pairs.append(("exception", str(line.attributes["exception.stacktrace"])))
    elif line.attributes.get("code.stacktrace"):
        pairs.append(("stack", str(line.attributes["code.stacktrace"])))
    return pairs


def _source_of(label: str, module: str) -> str:
    """The row's source: the stream's, but the server's and the CLI's by module, as they always were."""
    if label in ("server", "cli"):
        return "cli" if module.startswith("CLI.") else "server"
    return label


def _row(line: Line, label: str) -> dict[str, Any]:
    """A line as a row of the admin page (and the tools' results).

    Includes ``level_html`` / ``module_html`` / ``message_html`` fields with ``<span>`` wrappers for colour
    rendering. Raw ``level``, ``module``, and ``message`` are kept for filtering and sorting.
    """
    level, module, message = line.level, line.scope, line.body
    ts_num = line.at.timestamp()
    source = _source_of(label, module)
    is_startup = message.startswith(_STARTUP_MESSAGE)
    message_html = (
        f'<span class="log-startup-msg">{_html.escape(message)}</span>'
        if is_startup
        else _html.escape(message)
    )
    pairs = _pairs_of(line)
    scope = {k: str(v) for k, v in line.attributes.items() if k in _SCOPE_KEYS and v}
    return {
        "id": f"{source}:{ts_num}",             # deterministic row key for selection persistence
        "timestamp": ts_num,                    # epoch float — numeric sort key
        "timestamp_display": _to_12h(ts_num),   # "2:32:05 PM" for Time column
        "date_display": _format_date(ts_num),   # "Mar 18" for Date column
        "level": level,
        "level_html": f'<span class="{_LEVEL_CSS_CLASS.get(level, "")}">{level}</span>',
        "module": module,
        "module_html": f'<span class="log-mod-{_module_color_idx(module)}">{module}</span>',
        "message": message,
        "message_html": message_html,
        "extra": " ".join(f"{k}={v}" for k, v in pairs),
        "extra_html": _pairs_html(pairs, rows=False),
        "extra_tooltip_html": _pairs_html(pairs, rows=True),
        # The fields as pairs, so nothing has to split `extra` again (a traceback holds spaces and "=")
        "fields": [[k, v] for k, v in pairs],
        "source": source,
        "is_startup": is_startup,
        # Structured scope fields — used for icon display and exact-match filtering.
        "scope_device_id": scope.get("device_id", ""),
        "scope_msg_id": scope.get("msg_id", ""),
        "scope_method": scope.get("method", ""),
        "scope_text_preview": scope.get("text_preview", ""),
        "scope_traffic_class": scope.get("traffic_class", ""),
        "scope_traffic_subclass": scope.get("traffic_subclass", ""),
        "has_msg_id": bool(scope.get("msg_id")),
        # The story the line belongs to and its step (W3C TraceId, SpanId), when it was logged inside one: a chat
        # message's story id comes from the message's id, and its graph run carries the same id.
        "story_id": line.trace_id or "",
        "step_id": line.span_id or "",
    }


def _parse_stderr_line(
    path: Path,
    source: str,
    line: str,
    index: int,
    base_timestamp: float,
) -> dict[str, Any] | None:
    """Convert a plain stderr line into a log row for startup crash visibility."""
    message = line.rstrip("\r\n")
    if not message.strip():
        return None
    ts_num = base_timestamp + (index / 1_000_000)
    level = "ERROR"
    module = "STDERR"
    pairs = [("file", str(path))]
    return {
        "id": f"{source}:{path}:{index}:{ts_num}",
        "timestamp": ts_num,
        "timestamp_display": _to_12h(ts_num),
        "date_display": _format_date(ts_num),
        "level": level,
        "level_html": f'<span class="{_LEVEL_CSS_CLASS.get(level, "")}">{level}</span>',
        "module": module,
        "module_html": f'<span class="log-mod-{_module_color_idx(module)}">{module}</span>',
        "message": message,
        "message_html": _html.escape(message),
        "extra": f"file={path}",
        "extra_html": _pairs_html(pairs, rows=False),
        "extra_tooltip_html": _pairs_html(pairs, rows=True),
        "fields": [[k, v] for k, v in pairs],
        "source": source,
        "is_startup": False,
    }


def _rows_of_text(text: str, label: str) -> list[dict[str, Any]]:
    rows = []
    for raw in text.splitlines():
        parsed = parse(raw)
        if parsed is not None:
            rows.append(_row(parsed, label))
    return rows


def _plain_rows(path: Path, source: str, lines: list[str], start: int) -> list[dict[str, Any]]:
    base_timestamp = path.stat().st_mtime
    rows = []
    for index, text in enumerate(lines, start=start):
        parsed = _parse_stderr_line(path, source, text, index, base_timestamp)
        if parsed is not None:
            rows.append(parsed)
    return rows


# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------


def _read_all_rows(path: Path, source: str) -> list[dict[str, Any]]:
    """Every row of one file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.debug("A log file couldn't be read", file=str(path), error=str(exc))
        return []
    if path.suffix == ".log":
        return _plain_rows(path, source, text.splitlines(), 0)
    return _rows_of_text(text, source)


def _read_tail_rows(path: Path, source: str, n: int) -> tuple[list[dict[str, Any]], int]:
    """The last *n* rows of one file, and its size (the offset to poll from)."""
    try:
        size = path.stat().st_size
    except OSError:
        return [], 0
    try:
        if path.suffix == ".log":
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(0, len(lines) - n)
            return _plain_rows(path, source, lines[start:], start), size
        want = _TAIL_READ_BYTES
        while True:
            seek_pos = max(0, size - want)
            with path.open("rb") as fh:
                fh.seek(seek_pos)
                chunk = fh.read(size - seek_pos).decode("utf-8", errors="replace")
            if seek_pos > 0:
                chunk = chunk.partition("\n")[2]  # the first line may be cut: drop it
            rows = _rows_of_text(chunk, source)
            if len(rows) >= n or seek_pos == 0:
                break
            want *= 2
    except OSError as exc:
        log.debug("A log file couldn't be read", file=str(path), error=str(exc))
        return [], size
    return (rows[-n:] if len(rows) > n else rows), size


def _read_rows_from_offset(path: Path, source: str, offset: int) -> tuple[list[dict[str, Any]], int]:
    """The rows written after *offset* bytes, and the new offset (only whole lines: a line being written waits for
    the next poll)."""
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read()
    except OSError as exc:
        log.debug("A log file couldn't be read", file=str(path), error=str(exc))
        return [], offset
    if not chunk:
        return [], offset
    if path.suffix == ".log":
        text = chunk.decode("utf-8", errors="replace")
        return _plain_rows(path, source, text.splitlines(), offset), offset + len(chunk)
    whole = chunk.rfind(b"\n") + 1
    if whole == 0:
        return [], offset
    return _rows_of_text(chunk[:whole].decode("utf-8", errors="replace"), source), offset + whole


def _stream_tail(stream: LogStream, n: int) -> list[dict[str, Any]]:
    """The last *n* rows of a stream, across its days (newest file first, until there are enough)."""
    gathered: list[list[dict[str, Any]]] = []
    count = 0
    for _day, path in stream.files():
        rows, _size = _read_tail_rows(path, stream.label, n - count)
        gathered.append(rows)
        count += len(rows)
        if count >= n:
            break
    return [r for rows in reversed(gathered) for r in rows]


def _stream_since(stream: LogStream, min_ts: float) -> list[dict[str, Any]]:
    """Every row of a stream at or after *min_ts* (whole days read, newest first, up to _TAIL_SINCE_MAX_LINES)."""
    first_day = datetime.datetime.fromtimestamp(min_ts).astimezone().date()
    gathered: list[list[dict[str, Any]]] = []
    count = 0
    for day, path in stream.files():
        if day is not None and day < first_day:
            break
        rows = [r for r in _read_all_rows(path, stream.label) if float(r["timestamp"]) >= min_ts]
        gathered.append(rows)
        count += len(rows)
        if count >= _TAIL_SINCE_MAX_LINES:
            break
    rows = [r for rows in reversed(gathered) for r in rows]
    return rows[-_TAIL_SINCE_MAX_LINES:]


def _stream_search_rows(stream: LogStream) -> list[dict[str, Any]]:
    """The rows a search reads: the newest files, until _SEARCH_BYTES (at least one)."""
    gathered: list[list[dict[str, Any]]] = []
    budget = _SEARCH_BYTES
    for _day, path in stream.files():
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if gathered and size > budget:
            break
        gathered.append(_read_all_rows(path, stream.label))
        budget -= size
    return [r for rows in reversed(gathered) for r in rows]


def find_last_server_session_start_ts(workspace: str | None) -> float | None:
    """Epoch timestamp of the latest server startup line (``🚀 Hiro Server starting``), if any.

    The server's files are read newest first; the newest file that holds one gives its last.
    """
    log_dir = _resolve_log_dir(workspace)
    for _day, path in LogStream("server", log_dir, "server").files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.debug("A log file couldn't be read", file=str(path), error=str(exc))
            continue
        last: float | None = None
        for raw in text.splitlines():
            if _STARTUP_MESSAGE not in raw:
                continue
            parsed = parse(raw)
            if parsed is not None and parsed.body.startswith(_STARTUP_MESSAGE):
                ts = parsed.at.timestamp()
                last = ts if last is None or ts > last else last
        if last is not None:
            return last
    return None


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------


def _apply_level_filter(rows: list[dict], min_level: str | None) -> list[dict]:
    if not min_level:
        return rows
    min_order = _LEVEL_ORDER.get(min_level.upper(), 0)
    return [r for r in rows if _LEVEL_ORDER.get(r.get("level", ""), 0) >= min_order]


def _apply_module_filter(rows: list[dict], module: str | None) -> list[dict]:
    if not module:
        return rows
    m = module.lower()
    return [r for r in rows if m in r.get("module", "").lower()]


def _apply_query_filter(rows: list[dict], query: str | None) -> list[dict]:
    if not query:
        return rows
    q = query.lower()
    return [
        r
        for r in rows
        if q in r.get("message", "").lower() or q in r.get("extra", "").lower()
    ]


def _apply_scope_filter(
    rows: list[dict],
    *,
    device_id: str | None = None,
    msg_id: str | None = None,
    method: str | None = None,
    traffic_classes: list[str] | None = None,
    story_id: str | None = None,
) -> list[dict]:
    """Exact-match filter on parsed scope fields (device_id / msg_id / method / traffic_class), and on the story.

    Filters AND together: a row must satisfy every non-None constraint. ``traffic_classes``
    is OR within itself (any-of) and AND with the others.
    """
    device_id = (device_id or "").strip() or None
    msg_id = (msg_id or "").strip() or None
    method = (method or "").strip() or None
    tcl_set = {tc.strip() for tc in (traffic_classes or []) if tc and tc.strip()} or None
    story_id = story_id_of(story_id) if (story_id or "").strip() else None
    if not any([device_id, msg_id, method, tcl_set, story_id]):
        return rows
    result = rows
    if story_id:
        result = [r for r in result if r.get("story_id") == story_id]
    if device_id:
        result = [r for r in result if r.get("scope_device_id") == device_id]
    if msg_id:
        # The message's lines, and every line of its story: its timed steps, its AI calls, its run (the story's id
        # comes from the message's own id)
        story_id = story.id_for(msg_id)
        result = [r for r in result if r.get("scope_msg_id") == msg_id or r.get("story_id") == story_id]
    if method:
        result = [r for r in result if r.get("scope_method") == method]
    if tcl_set:
        result = [r for r in result if r.get("scope_traffic_class") in tcl_set]
    return result


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class LogSearchResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    total_matches: int = 0
    truncated: bool = False


@dataclass
class LogTailResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    # JSON-serialisable {str(file_path): byte_offset} — pass back as
    # after_offsets on the next LogTailTool call for incremental polling.
    file_offsets: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class LogSearchTool(Tool):
    name = "log_search"
    description = (
        "Search the logs of the core (server, channels, gateway, CLI) and of every app for entries matching "
        "the given filters. Rows are returned sorted by timestamp."
    )
    params = {
        "source": ToolParam(
            str,
            _SOURCE_HELP,
            required=False,
        ),
        "level": ToolParam(
            str,
            "Minimum log level: DEBUG, INFO, WARNING, ERROR, or CRITICAL",
            required=False,
        ),
        "module": ToolParam(
            str,
            "Filter by module name (case-insensitive substring match)",
            required=False,
        ),
        "query": ToolParam(
            str,
            "Full-text search across message and extra fields (case-insensitive)",
            required=False,
        ),
        "device_id": ToolParam(
            str,
            "Exact-match filter on the device_id scope field (UUID of a paired device)",
            required=False,
        ),
        "msg_id": ToolParam(
            str,
            "Exact-match filter on the msg_id scope field (routing.id of a user message), with every line of that "
            "message's story (its timed steps and AI calls)",
            required=False,
        ),
        "method": ToolParam(
            str,
            "Exact-match filter on the method scope field (e.g. 'channels.list', 'policy.get')",
            required=False,
        ),
        "traffic_class": ToolParam(
            str,
            "Filter by Tier-1 traffic_class (e.g. 'inbound.message', 'outbound.response'). "
            "Comma-separated for multi-select; matches any.",
            required=False,
        ),
        "story_id": ToolParam(
            str,
            "Only the lines of this story (its 32-hex id, a W3C traceparent, or a chat message's id), from every source",
            required=False,
        ),
        "limit": ToolParam(
            int,
            f"Maximum rows to return (default {_DEFAULT_SEARCH_LIMIT})",
            required=False,
        ),
        "workspace": ToolParam(
            str,
            "Workspace name (default: registry default)",
            required=False,
        ),
    }

    def execute(
        self,
        source: str | None = None,
        level: str | None = None,
        module: str | None = None,
        query: str | None = None,
        device_id: str | None = None,
        msg_id: str | None = None,
        method: str | None = None,
        traffic_class: str | list[str] | None = None,
        limit: int | None = None,
        workspace: str | None = None,
        story_id: str | None = None,
    ) -> LogSearchResult:
        log_dir = _resolve_log_dir(workspace)
        gateway_log_dir = _resolve_gateway_log_dir()
        effective_limit = limit if limit is not None else _DEFAULT_SEARCH_LIMIT

        device_id = (device_id or "").strip() or None
        msg_id = (msg_id or "").strip() or None
        method = (method or "").strip() or None
        if isinstance(traffic_class, str):
            traffic_classes = [tc.strip() for tc in traffic_class.split(",") if tc.strip()]
        elif isinstance(traffic_class, list):
            traffic_classes = [str(tc).strip() for tc in traffic_class if str(tc).strip()]
        else:
            traffic_classes = []

        all_rows: list[dict] = []
        for stream in _collect_log_files(log_dir, gateway_log_dir, source or "all"):
            all_rows.extend(_stream_search_rows(stream))

        all_rows = _keep_source(all_rows, source)
        all_rows = _apply_level_filter(all_rows, level)
        all_rows = _apply_module_filter(all_rows, module)
        all_rows = _apply_query_filter(all_rows, query)
        all_rows = _apply_scope_filter(
            all_rows,
            device_id=device_id,
            msg_id=msg_id,
            method=method,
            traffic_classes=traffic_classes or None,
            story_id=story_id,
        )
        all_rows.sort(key=lambda r: float(r.get("timestamp", 0)))

        total = len(all_rows)
        truncated = total > effective_limit
        # Keep the MOST RECENT matches, not the oldest. Slicing [:limit] after an
        # ascending sort would drop newest rows, so admin filters appeared to lag
        # by hours when total matches exceeded the limit.
        rows_window = all_rows[-effective_limit:] if truncated else all_rows
        return LogSearchResult(
            rows=rows_window,
            total_matches=total,
            truncated=truncated,
        )


class LogTailTool(Tool):
    name = "log_tail"
    description = (
        "Return the most recent log entries. To tail live, pass the "
        "file_offsets JSON from a previous result back as after_offsets — "
        "only new lines written since that call are returned."
    )
    params = {
        "source": ToolParam(
            str,
            _SOURCE_HELP,
            required=False,
        ),
        "lines": ToolParam(
            int,
            f"Number of recent lines for the initial load (default {_DEFAULT_TAIL_LINES})",
            required=False,
        ),
        "after_offsets": ToolParam(
            str,
            "JSON string of {file_path: byte_offset} from a previous LogTailResult "
            "for incremental polling — only new lines are returned",
            required=False,
        ),
        "workspace": ToolParam(
            str,
            "Workspace name (default: registry default)",
            required=False,
        ),
        "min_timestamp": ToolParam(
            float,
            "If set (initial load only), only rows with timestamp >= this epoch value are returned.",
            required=False,
        ),
    }

    def execute(
        self,
        source: str | None = None,
        lines: int | None = None,
        after_offsets: str | None = None,
        workspace: str | None = None,
        min_timestamp: float | None = None,
    ) -> LogTailResult:
        log_dir = _resolve_log_dir(workspace)
        gateway_log_dir = _resolve_gateway_log_dir()
        n = lines if lines is not None else _DEFAULT_TAIL_LINES

        prev_offsets: dict[str, int] = {}
        if after_offsets:
            try:
                prev_offsets = json.loads(after_offsets)
            except (ValueError, TypeError) as exc:
                log.debug("after_offsets isn't JSON: a fresh tail instead", error=str(exc))

        streams = _collect_log_files(log_dir, gateway_log_dir, source or "all")
        all_rows: list[dict] = []
        new_offsets: dict[str, int] = {}

        for stream in streams:
            if prev_offsets:
                # Polling: what each followed file gained since the last call. A file that appeared since (a new
                # day, a channel that started) is read from its start.
                for path in stream.recent():
                    rows, offset = _read_rows_from_offset(path, stream.label, int(prev_offsets.get(str(path), 0)))
                    all_rows.extend(rows)
                    new_offsets[str(path)] = offset
                continue
            # Initial: the last n rows, or every row since *min_timestamp* when set.
            if min_timestamp is not None:
                all_rows.extend(_stream_since(stream, float(min_timestamp)))
            else:
                all_rows.extend(_stream_tail(stream, n))
            for path in stream.recent():
                try:
                    new_offsets[str(path)] = path.stat().st_size
                except OSError:
                    new_offsets[str(path)] = 0

        all_rows = _keep_source(all_rows, source)
        all_rows.sort(key=lambda r: float(r.get("timestamp", 0)))
        return LogTailResult(rows=all_rows, file_offsets=new_offsets)


# ---------------------------------------------------------------------------
# One question across every part: the problems in a span, a whole story
# ---------------------------------------------------------------------------

_PROBLEM_LEVEL = "WARNING"
_DEFAULT_SPAN = "1h"
_DEFAULT_PROBLEM_ROWS = 100
_DEFAULT_STORY_ROWS = 1000
_SPAN = re.compile(r"^\s*(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>s|sec|m|min|h|hr|hour|hours|d|day|days)\s*$", re.I)
_UNIT_SECONDS = {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600,
                 "d": 86400, "day": 86400, "days": 86400}
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_SAMPLES = 3
_VARIES = re.compile(r"\b[0-9a-f]*\d[0-9a-f]*\b", re.I)  # numbers and hex ids: what changes between repeats


def _kind(message: str) -> str:
    """A message with its numbers and ids blanked: "retrying in 5 s" and "retrying in 10 s" are one kind."""
    return _VARIES.sub("#", message)

_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-(?P<trace>[0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")
# A line at WARNING or above, read off the raw text before parsing it (the foundation writes compact JSON)
_PROBLEM_MARKS = ('"SeverityNumber":13', '"SeverityNumber":17', '"SeverityNumber":21', '"SeverityText":"WARNING"',
                  '"SeverityText":"ERROR"', '"SeverityText":"CRITICAL"')


def moment(value: str | float | None, *, now: float | None = None) -> float | None:
    """A moment as epoch seconds: a span back from now ("90m", "1h", "2d"), an ISO time ("2026-11-20T13:15", the
    house's time when it names no zone), or epoch seconds. None when empty; ValueError when unreadable."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip()
    now = time.time() if now is None else now
    m = _SPAN.match(text)
    if m:
        return now - float(m["n"]) * _UNIT_SECONDS[m["unit"].lower()]
    try:
        return float(text)
    except ValueError:
        pass
    try:
        at = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Not a time or a span: {value!r} (say '1h', '30m', '2d' or an ISO time).") from exc
    return (at if at.tzinfo else at.astimezone()).timestamp()


def story_id_of(value: str) -> str:
    """The story id a value names: a story id (32 hex digits), a W3C traceparent, or any other id (a chat message's
    id gives its story's, story.id_for)."""
    text = (value or "").strip().lower()
    if _HEX32.match(text):
        return text
    m = _TRACEPARENT.match(text)
    if m:
        return m["trace"]
    return story.id_for((value or "").strip())


def _when(ts: float) -> str:
    """A row's time for people: "Today, 1:15:46 PM"."""
    dt = _epoch_to_dt(ts)
    return human_datetime(dt, seconds=True) if dt is not None else str(ts)


def brief(row: dict[str, Any]) -> dict[str, Any]:
    """A row as an agent reads it: no HTML, the time in words, the fields as a dict."""
    out: dict[str, Any] = {
        "when": _when(float(row.get("timestamp", 0))),
        "timestamp": row.get("timestamp"),
        "source": row.get("source", ""),
        "level": row.get("level", ""),
        "area": row.get("module", ""),
        "message": row.get("message", ""),
    }
    fields = {k: v for k, v in (row.get("fields") or [])}
    if fields:
        out["fields"] = fields
    if row.get("story_id"):
        out["story_id"] = row["story_id"]
    return out


def _read_matching(path: Path, label: str, marks: tuple[str, ...], since: float | None = None) -> list[dict[str, Any]]:
    """The rows of one file whose raw line holds one of `marks` (cheap: only those are parsed), at or after `since`.
    A plain stderr file's rows are all errors: all of them."""
    if path.suffix == ".log":
        rows = _read_all_rows(path, label)
    else:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.debug("A log file couldn't be read", file=str(path), error=str(exc))
            return []
        rows = [_row(parsed, label) for raw in text.splitlines()
                if any(mk in raw for mk in marks) and (parsed := parse(raw)) is not None]
    if since is not None:
        rows = [r for r in rows if float(r["timestamp"]) >= since]
    return rows


def _streams_rows(streams: list[LogStream], marks: tuple[str, ...], since: float | None) -> list[dict[str, Any]]:
    """Every stream's rows holding a mark: the days from `since` on (or the newest files up to the search budget)."""
    first_day = datetime.datetime.fromtimestamp(since).astimezone().date() if since is not None else None
    rows: list[dict[str, Any]] = []
    for stream in streams:
        budget = _SEARCH_BYTES
        for day, path in stream.files():
            if first_day is not None and day is not None and day < first_day:
                break  # a line is never in an earlier day's file than its own (the store writes late lines later)
            if first_day is None:
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if budget < _SEARCH_BYTES and size > budget:
                    break
                budget -= size
            rows.extend(_read_matching(path, stream.label, marks, since))
    return rows


@dataclass
class LogProblemsResult:
    span: str = ""  # the span in words: "Today, 12:15:00 PM to Today, 1:15:00 PM"
    total: int = 0
    by_source: dict[str, int] = field(default_factory=dict)  # problems per source, most first
    # One per part, level and area: count, kinds (how many different messages), messages (the latest few kinds),
    # first and last time (words), a few story ids; errors first, then the most frequent
    groups: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)  # the newest problems, brief rows, oldest first
    truncated: bool = False


class LogProblemsTool(Tool):
    name = "log_problems"
    description = (
        "What went wrong in a span of time, across the core (server, channels, gateway, CLI) and every app: the "
        "warnings and errors of every part, grouped by part and area (with counts, the latest messages, first and last "
        "time, and story ids to follow with log_story), and the newest problem lines with their fields and tracebacks."
    )
    params = {
        "since": ToolParam(
            str,
            "Start of the span: back from now ('1h', '30m', '2d') or an ISO time (default '1h')",
            required=False,
        ),
        "until": ToolParam(str, "End of the span: back from now or an ISO time (default: now)", required=False),
        "level": ToolParam(str, "Lowest level counted: WARNING (default), ERROR or CRITICAL", required=False),
        "source": ToolParam(str, _SOURCE_HELP, required=False),
        "limit": ToolParam(int, f"How many problem lines to return (default {_DEFAULT_PROBLEM_ROWS})", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        since: str | None = None,
        until: str | None = None,
        level: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        workspace: str | None = None,
    ) -> LogProblemsResult:
        now = time.time()
        start = moment(since or _DEFAULT_SPAN, now=now)
        end = moment(until, now=now) or now
        assert start is not None
        lowest = (level or _PROBLEM_LEVEL).upper()
        if _LEVEL_ORDER.get(lowest, 0) < _LEVEL_ORDER[_PROBLEM_LEVEL]:
            lowest = _PROBLEM_LEVEL  # a problem is a warning or worse: search the rest with log_search
        streams = _collect_log_files(_resolve_log_dir(workspace), _resolve_gateway_log_dir(), source or "all")
        rows = _streams_rows(streams, _PROBLEM_MARKS, start)
        rows = _keep_source(rows, source)
        rows = [r for r in _apply_level_filter(rows, lowest) if float(r["timestamp"]) <= end]
        rows.sort(key=lambda r: float(r.get("timestamp", 0)))

        # One group per part, level and area: the same problem often names something different each time (a person,
        # a camera, a retry's delay), so a group shows how many kinds of message it holds and the latest few.
        groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        by_source: dict[str, int] = {}
        for r in reversed(rows):  # newest first: a group's samples are its latest
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
            key = (r["source"], r["level"], r["module"])
            g = groups.get(key)
            if g is None:
                g = groups[key] = {"source": key[0], "level": key[1], "area": key[2], "count": 0, "kinds": set(),
                                   "messages": [], "first": r["timestamp"], "last": r["timestamp"], "story_ids": []}
            g["count"] += 1
            g["first"] = r["timestamp"]
            kind = _kind(r["message"])
            if kind not in g["kinds"]:
                g["kinds"].add(kind)
                if len(g["messages"]) < _SAMPLES:
                    g["messages"].append(r["message"])
            if r.get("story_id") and r["story_id"] not in g["story_ids"] and len(g["story_ids"]) < _SAMPLES:
                g["story_ids"].append(r["story_id"])
        ordered = sorted(groups.values(), key=lambda g: (-_LEVEL_ORDER.get(g["level"], 0), -g["count"]))
        for g in ordered:
            g["first"], g["last"] = _when(float(g["first"])), _when(float(g["last"]))
            g["kinds"] = len(g["kinds"])
        n = limit if limit is not None else _DEFAULT_PROBLEM_ROWS
        return LogProblemsResult(
            span=f"{_when(start)} to {_when(end)}",
            total=len(rows),
            by_source=dict(sorted(by_source.items(), key=lambda kv: -kv[1])),
            groups=ordered,
            rows=[brief(r) for r in rows[-n:]] if n > 0 else [],
            truncated=len(rows) > n,
        )


@dataclass
class LogStoryResult:
    story_id: str = ""
    sources: list[str] = field(default_factory=list)  # the parts it went through, in the order it reached them
    started: str = ""  # its first line's time, in words
    took_ms: int = 0  # from its first line to its last
    problems: int = 0  # its lines at WARNING or above
    # Its timed steps, in order: step, source, elapsed_ms, outcome, when, step_id, parent_step
    steps: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)  # every line, brief, in order
    truncated: bool = False


class LogStoryTool(Tool):
    name = "log_story"
    description = (
        "Everything one story did, across the core and every app, in order: every line logged under its id (a page "
        "request, a camera check, a chat message from the phone to the reply), its timed steps with how long each "
        "took, and which parts it went through. Give a story id (from a log line or log_problems), a W3C traceparent, "
        "or a chat message's id."
    )
    params = {
        "story_id": ToolParam(str, "The story's id (32 hex digits), a traceparent, or a chat message's id"),
        "limit": ToolParam(int, f"How many lines at most (default {_DEFAULT_STORY_ROWS})", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, story_id: str, limit: int | None = None, workspace: str | None = None) -> LogStoryResult:
        sid = story_id_of(story_id)
        streams = _collect_log_files(_resolve_log_dir(workspace), _resolve_gateway_log_dir(), "all")
        streams = [s for s in streams if s.plain is None]  # a plain stderr line has no story
        rows = [r for r in _streams_rows(streams, (sid,), None) if r.get("story_id") == sid]
        rows.sort(key=lambda r: float(r.get("timestamp", 0)))
        n = limit if limit is not None else _DEFAULT_STORY_ROWS
        result = LogStoryResult(story_id=sid, truncated=len(rows) > n)
        if not rows:
            return result
        for r in rows:
            if r["source"] not in result.sources:
                result.sources.append(r["source"])
            fields = {k: v for k, v in (r.get("fields") or [])}
            if "step" in fields and "elapsed_ms" in fields:
                step = {"step": fields["step"], "source": r["source"], "elapsed_ms": _number(fields["elapsed_ms"]),
                        "outcome": fields.get("outcome", ""), "when": _when(float(r["timestamp"])),
                        "step_id": r.get("step_id", "")}
                if fields.get("parent_step"):
                    step["parent_step"] = fields["parent_step"]
                result.steps.append(step)
        first, last = float(rows[0]["timestamp"]), float(rows[-1]["timestamp"])
        result.started = _when(first)
        result.took_ms = round((last - first) * 1000)
        result.problems = len(_apply_level_filter(rows, _PROBLEM_LEVEL))
        result.rows = [brief(r) for r in rows[:n]]
        return result


def _number(value: Any) -> float | int | str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return int(f) if f.is_integer() else f
