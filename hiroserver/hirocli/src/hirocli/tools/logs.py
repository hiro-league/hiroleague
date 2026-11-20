"""Log reading tools: search and tail the server, channel, gateway and CLI log files.

These tools read the core's daily log files, written through the logging foundation (hiro_commons.log:
`Logger.start`): one JSON line per record with OpenTelemetry's field names, one file a day, kept 30 days.
They are available to the AI agent (for natural-language log queries), the CLI (`hiro logs search/tail`), and the
admin UI (direct import).

The files, in the workspace's logs folder (and the gateway's):
- `server-<YYYY-MM-DD>.jsonl`: the server process;
- `cli-<YYYY-MM-DD>.jsonl`: every `hiro` command;
- `channel-<name>-<YYYY-MM-DD>.jsonl`: each channel plugin;
- `gateway-<YYYY-MM-DD>.jsonl`, and the gateway instance's `stderr.log` (a crash before its logging started).

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger
from hiro_commons.logging_foundation import daily, story
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


def has_files(folder: Path | None, name: str) -> bool:
    return folder is not None and bool(daily.files(folder, name))


def _collect_log_files(
    log_dir: Path,
    gateway_log_dir: Path | None,
    source: str,
) -> list[LogStream]:
    """The streams for the requested source(s)."""
    streams: list[LogStream] = []
    src = (source or "all").lower()

    # The server's and the CLI's files are read together: each row's source comes from its module (see _source_of).
    if src in ("all", "server", "cli"):
        streams.append(LogStream("server", log_dir, "server"))
        streams.append(LogStream("cli", log_dir, "cli"))

    if src in ("all", "channels"):
        for channel in channel_names(log_dir):
            streams.append(LogStream(f"channel-{channel}", log_dir, f"channel-{channel}"))

    if src in ("all", "gateway") and gateway_log_dir is not None:
        streams.append(LogStream("gateway", gateway_log_dir, "gateway"))

    if src in ("all", "gateway"):
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
) -> list[dict]:
    """Exact-match filter on parsed scope fields (device_id / msg_id / method / traffic_class).

    Filters AND together: a row must satisfy every non-None constraint. ``traffic_classes``
    is OR within itself (any-of) and AND with the others.
    """
    device_id = (device_id or "").strip() or None
    msg_id = (msg_id or "").strip() or None
    method = (method or "").strip() or None
    tcl_set = {tc.strip() for tc in (traffic_classes or []) if tc and tc.strip()} or None
    if not any([device_id, msg_id, method, tcl_set]):
        return rows
    result = rows
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
        "Search server, channel, gateway, and CLI log files for entries matching "
        "the given filters. Rows are returned sorted by timestamp."
    )
    params = {
        "source": ToolParam(
            str,
            "Log source: 'server', 'channels', 'gateway', 'cli', or 'all' (default: 'all')",
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
            "Log source: 'server', 'channels', 'gateway', 'cli', or 'all' (default: 'all')",
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
