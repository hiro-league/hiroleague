"""The device app's problems, into the core's log store: the ``logs.report`` request (the logging plan, phase 8).

The phone sends only its problems (each warning and error it logs, and every error nobody caught), never its full log
(Later, in the plan). Each arrives in a small shape of the phone's own (device_apps' ``device_problems.dart``) and
becomes one line in the foundation's format in the store's ``device`` stream, beside the apps' streams, so the log
tools answer across it too:

- ``Resource``: ``service.name`` ``device``; the sending device's id is the field ``device_id`` (the core's own scope key,
  so the log tools' device filter finds it: the reader keeps only ``service.name`` from ``Resource``);
- ``TraceId``: the story it belongs to. A problem made while a chat message was being sent names that message's own
  id (``story``), and the core turns it into the story's id as it does for the message itself (``story.id_for``), so
  it shows under that message's story;
- what a person said never comes along: the phone leaves it out, and this side hides it again, with every field whose
  name says it holds a secret (the foundation's rule), and cuts each value to size.

A batch sent again (the connection dropped before the phone heard the answer) is kept once: each problem has its own
id, and the ids of the last few thousand are remembered.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime
from typing import Any

from hiro_channel_sdk.constants import METHOD_LOGS_REPORT
from hiro_commons.logging_foundation import line, story

from ..services import log_store
from .request_handler import DEVICES_ONLY, RequestContext, RequestRefused

METHOD = METHOD_LOGS_REPORT
STREAM = "device"
INVALID = "invalid"
MAX_LINES = 20  # per batch: the phone sends 20 at most
_SEEN_MAX = 5000
_seen: OrderedDict[str, None] = OrderedDict()

_LEVELS = {"WARNING": 13, "ERROR": 17}
# A person's words: never in a line from the phone (the core's own lines keep only a short preview, on purpose).
_WORDS = frozenset({"text", "body", "content", "transcript", "prompt", "caption", "message_text"})


def _cut(value: Any, size: int) -> str:
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= size else text[: size - 1] + "…"


def _safe_fields(fields: Any) -> dict[str, Any]:
    if not isinstance(fields, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in list(fields.items())[:20]:
        name = _cut(key, 60)
        if line.is_secret(name) or name.lower() in _WORDS:
            out[name] = line.HIDDEN
        elif value is None or isinstance(value, (bool, int, float)):
            out[name] = value
        else:
            out[name] = _cut(value, 200)
    return out


def _story_id(ref: Any) -> str | None:
    return story.id_for(_cut(ref, 100)) if isinstance(ref, str) and ref.strip() else None


def to_line(problem: Any, device_id: str) -> dict[str, Any] | None:
    """One problem from the phone as a line of the store, or None when it isn't one."""
    if not isinstance(problem, dict) or not isinstance(problem.get("message"), str):
        return None
    level = problem.get("level") if problem.get("level") in _LEVELS else "WARNING"
    try:
        seen_at = datetime.fromisoformat(str(problem.get("at")).replace("Z", "+00:00"))
        timestamp = seen_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except ValueError:
        return None
    attributes = {**_safe_fields(problem.get("fields")), "device_id": device_id}  # the sender, never the phone's word
    if problem.get("error_type"):
        attributes["exception.type"] = _cut(problem["error_type"], 200)
    if problem.get("error_message"):
        attributes["exception.message"] = _cut(problem["error_message"], 2000)
    if problem.get("stack"):
        attributes["exception.stacktrace"] = _cut(problem["stack"], 8000)
    if problem.get("story"):
        attributes["message_id"] = _cut(problem["story"], 100)
    if isinstance(problem.get("id"), str):
        attributes["log.record.uid"] = _cut(problem["id"], 100)  # the phone's own id for it (OpenTelemetry's name)
    out: dict[str, Any] = {
        "Timestamp": timestamp,
        "SeverityText": level,
        "SeverityNumber": _LEVELS[level],
        "Body": _cut(" ".join(problem["message"].split()), 500),
        "InstrumentationScope": f"device.{_cut(problem.get('area') or 'app', 100)}",
    }
    story_id = _story_id(problem.get("story"))
    if story_id:
        out["TraceId"] = story_id
    if attributes:
        out["Attributes"] = attributes
    out["Resource"] = {"service.name": STREAM}
    return out


def _remember(problem_ids: list[str]) -> None:
    """Ids kept in the store: a batch sent again is dropped (after the write, so a failed one is tried again)."""
    for problem_id in problem_ids:
        _seen[problem_id] = None
        _seen.move_to_end(problem_id)
    while len(_seen) > _SEEN_MAX:
        _seen.popitem(last=False)


async def handle_logs_report(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    items = params.get("lines")
    if not isinstance(items, list):
        raise RequestRefused(INVALID, "lines is required: the phone's problems.")
    if len(items) > MAX_LINES:
        raise RequestRefused(INVALID, f"At most {MAX_LINES} problems in one batch.")
    device_id = _cut(ctx.msg.routing.sender_id or "", 100)
    lines: list[dict[str, Any]] = []
    ids: list[str] = []
    for problem in items:
        built = to_line(problem, device_id)
        raw_id = problem.get("id") if isinstance(problem, dict) else None
        problem_id = _cut(raw_id, 100) if isinstance(raw_id, str) else None
        if built is None or (problem_id is not None and (problem_id in _seen or problem_id in ids)):
            continue
        lines.append(built)
        if problem_id is not None:
            ids.append(problem_id)
    kept = await asyncio.to_thread(log_store.write, STREAM, lines) if lines else 0
    _remember(ids)
    return {"kept": kept}


DEVICE_PROBLEM_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD, handle_logs_report, DEVICES_ONLY),
)
