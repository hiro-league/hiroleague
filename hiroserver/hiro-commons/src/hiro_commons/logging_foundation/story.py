"""A story: everything one starting event caused, across every process, under one id, with each hop a timed step.

    from hiro_commons.logging_foundation import story

    with story.begin("gateway.relay", story_id=story.id_for(message_id)):   # this process's first step
        with story.step("ai.ask", area="AI.ASK", model=model) as step:     # a step under it
            ...
            step.set(tokens=tokens)                                         # more fields for its end line
        story.inject(frame_metadata)                                         # carried on to the next process

What it gives:
- **The story id and the step id** are OpenTelemetry's TraceId (32 hex digits) and SpanId (16): W3C Trace Context's
  format. A chat story takes the message's own id, which the device makes (`id_for`), so every process finds the same
  id even with nothing carried.
- **Every line logged inside a step carries `TraceId` and `SpanId`**, stamped in the caller's thread (line.py asks
  `current()`), standard logging and the core's structlog lines alike. `asyncio.to_thread` and new asyncio tasks keep
  them (contextvars); a queue between two tasks doesn't: put `carry()` beside the item and `begin(parent=...)` on the
  other side.
- **A step's end is one line** in its area, at its level: `"<name> took 12 ms"` (or `"... failed after 12 ms: <error>"`,
  at WARNING at least), with the fields `step`, `elapsed_ms`, `outcome` (ok, error, cancelled), `parent_step`, then the
  caller's. `line=False` keeps the ids and writes no end line (a step whose own code already logs its outcome).
- **Carrying it:** `carry()` is the current step as a W3C `traceparent`; `inject()` puts it in a mapping (HTTP headers,
  a frame's `routing.metadata`); `begin(parent=...)` continues it in the next process.

**A named story** (the logging plan's phase 6a) is one a feature says what it is: `named("net.health_checks",
title="42 checks, 1 changed")` inside its first step. Its name is declared once (`declare(Declared(...))`: the kit does it
from the app's `Extension(stories=...)`, the core from its own list) with one of the five kinds (`KINDS`): the kind says
how a person's view draws it, the name what people call it, the title this one time. Naming writes the story's first
line at INFO (the fields `story.kind`, `story.name`, `story.label`, `story.title`), and its step's end line goes at INFO
with them too, so both reach the core's log store, which lists stories from them. A story nobody names keeps its id
and isn't listed: a quiet timer round, a page read. A line outside any story is normal.

Only OpenTelemetry's Stable tracing API is used (`opentelemetry-api`: Span, SpanContext, its context, the W3C
propagator). There is no SDK, no exporter and no global tracer provider: a library that looks for one finds none. Our
own Span writes each step's end as a line in the process's own file.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
import time
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import (
    INVALID_SPAN,
    NonRecordingSpan,
    SpanContext,
    SpanKind,
    Status,
    StatusCode,
    TraceFlags,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.util.types import Attributes, AttributeValue

from . import bridge, line

__all__ = ["id_for", "begin", "step", "current", "current_id", "carry", "inject", "Step", "TRACEPARENT", "AREA",
           "KINDS", "Declared", "declare", "declared", "named", "retitle", "is_named"]

TRACEPARENT = "traceparent"  # W3C Trace Context's key, in headers and in a frame's metadata alike
AREA = "story"  # the area of a step's end line when the caller names none
_W3C = TraceContextTextMapPropagator()

# The five kinds of story (the logging plan's decision of Fri, Nov 20, 2026): one fixed list. A kind is how a person's
# view draws a story; adding one is a design decision, not a feature's.
KINDS = ("conversation", "event", "round", "action", "job")
_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")  # "<app or core part>.<story>": "net.health_checks"


@dataclass(frozen=True)
class Declared:
    """A story a feature declares: its name ("net.health_checks"), its kind, and what people call it ("Health
    checks")."""

    name: str
    kind: str
    label: str

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise ValueError(f"A story's name is '<part>.<story>' in lower case: {self.name!r}")
        if self.kind not in KINDS:
            raise ValueError(f"A story's kind is one of {', '.join(KINDS)}: {self.kind!r} ({self.name})")
        if not self.label.strip():
            raise ValueError(f"A story needs a label people read: {self.name}")


_declared: dict[str, Declared] = {}
_undeclared_warned: set[str] = set()


def declare(*stories: Declared) -> None:
    """Make these stories known to this process (once, at start). A name declared again with another kind or label
    is refused."""
    for d in stories:
        known = _declared.get(d.name)
        if known is not None and known != d:
            raise ValueError(f"The story {d.name} is declared twice, differently: {known} and {d}")
        _declared[d.name] = d


def declared() -> dict[str, Declared]:
    """The stories this process declared, by name."""
    return dict(_declared)


def id_for(any_id: str) -> str:
    """The story id a thing's own id gives, the same in every process: a uuid's 32 hex digits (a chat message's id),
    else the first 32 hex digits of the id's SHA-256."""
    text = str(any_id).strip()
    plain = text.replace("-", "").lower()
    if len(plain) == 32 and all(c in "0123456789abcdef" for c in plain) and int(plain, 16):
        return plain
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _new_id(bits: int) -> int:
    while True:
        found = random.getrandbits(bits)
        if found:  # W3C: all zeros is never a valid id
            return found


class Step(trace.Span):
    """One timed step of a story: an OpenTelemetry Span whose end is a line in the process's own file."""

    def __init__(self, name: str, trace_id: int, parent_id: int | None, *, area: str, level: int, line_: bool,
                 fields: Mapping[str, Any], box: dict[str, Any] | None = None) -> None:
        self._name = name
        # Shared by this process's steps of one story (a step under it gets its parent's): which one is named
        self._box: dict[str, Any] = box if box is not None else {}
        self._context = SpanContext(trace_id=trace_id, span_id=_new_id(64), is_remote=False,
                                    trace_flags=TraceFlags(TraceFlags.SAMPLED))
        self._parent_id = parent_id
        self._area, self._level, self._line = area, level, line_
        self._fields: dict[str, Any] = dict(fields)
        self._started = time.perf_counter()
        self._status = Status(StatusCode.UNSET)
        self._error: BaseException | None = None
        self._cancelled = False
        self._ended = False

    # -- ours ------------------------------------------------------------------------------------------------------

    @property
    def story_id(self) -> str:
        return trace.format_trace_id(self._context.trace_id)

    @property
    def step_id(self) -> str:
        return trace.format_span_id(self._context.span_id)

    def set(self, **fields: Any) -> None:
        """More fields for the step's end line."""
        self._fields.update(fields)

    def carry(self) -> str:
        """This step as a W3C traceparent."""
        return f"00-{self.story_id}-{self.step_id}-01"

    # -- OpenTelemetry's Span ------------------------------------------------------------------------------------

    def get_span_context(self) -> SpanContext:
        return self._context

    def set_attribute(self, key: str, value: AttributeValue) -> None:
        self._fields[key] = value

    def set_attributes(self, attributes: Mapping[str, AttributeValue]) -> None:
        self._fields.update(attributes)

    def add_event(self, name: str, attributes: Attributes = None, timestamp: int | None = None) -> None:
        pass  # a step's moments are log lines of their own

    def update_name(self, name: str) -> None:
        self._name = name

    def is_recording(self) -> bool:
        return not self._ended

    def set_status(self, status: Status | StatusCode, description: str | None = None) -> None:
        self._status = status if isinstance(status, Status) else Status(status, description)

    def record_exception(self, exception: BaseException, attributes: Attributes = None, timestamp: int | None = None,
                         escaped: bool = False) -> None:
        self._error = exception

    def end(self, end_time: int | None = None) -> None:
        if self._ended:
            return
        self._ended = True
        if self._line:
            self._write(round((time.perf_counter() - self._started) * 1000, 1))

    # -- the end line ---------------------------------------------------------------------------------------------

    def _write(self, elapsed_ms: float) -> None:
        failed = self._error is not None and not self._cancelled or self._status.status_code is StatusCode.ERROR
        outcome = "cancelled" if self._cancelled else ("error" if failed else "ok")
        level = max(self._level, logging.WARNING) if outcome == "error" else self._level
        if not bridge.passes(self._area, level):
            return
        fields: dict[str, Any] = {"step": self._name, "elapsed_ms": elapsed_ms, "outcome": outcome}
        if self._parent_id:
            fields["parent_step"] = trace.format_span_id(self._parent_id)
        if failed:
            err = self._error
            fields["error"] = str(err) if err is not None else (self._status.description or "")
            if err is not None:
                fields["error.type"] = type(err).__qualname__
            body = f"{self._name} failed after {_ms(elapsed_ms)}: {fields['error']}"
        elif outcome == "cancelled":
            body = f"{self._name} was cancelled after {_ms(elapsed_ms)}"
        else:
            body = f"{self._name} took {_ms(elapsed_ms)}"
        fields.update(self._fields)
        logger = logging.getLogger(self._area)
        record = logger.makeRecord(self._area, level, "(story)", 0, "%s", (body,), None,
                                   extra={line.ATTRIBUTES: fields, line.STORY: (self.story_id, self.step_id)})
        logger.handle(record)


def _ms(elapsed_ms: float) -> str:
    return f"{elapsed_ms:.0f} ms" if elapsed_ms >= 10 else f"{elapsed_ms} ms"


class _Tracer(trace.Tracer):
    """OpenTelemetry's Tracer over our Steps: a library handed it gets steps in our files. Not set as the global
    tracer provider."""

    def start_span(self, name: str, context: otel_context.Context | None = None, kind: SpanKind = SpanKind.INTERNAL,
                   attributes: Attributes = None, links: Sequence[trace.Link] | None = None,
                   start_time: int | None = None, record_exception: bool = True,
                   set_status_on_exception: bool = True) -> Step:
        parent_span = trace.get_current_span(context)
        parent = parent_span.get_span_context()
        if parent.is_valid:
            box = parent_span._box if isinstance(parent_span, Step) else None
            return Step(name, parent.trace_id, parent.span_id, area=AREA, level=logging.INFO, line_=True,
                        fields=dict(attributes or {}), box=box)
        return Step(name, _new_id(128), None, area=AREA, level=logging.INFO, line_=True, fields=dict(attributes or {}))

    @contextmanager
    def start_as_current_span(self, name: str, context: otel_context.Context | None = None,
                              kind: SpanKind = SpanKind.INTERNAL, attributes: Attributes = None,
                              links: Sequence[trace.Link] | None = None, start_time: int | None = None,
                              record_exception: bool = True, set_status_on_exception: bool = True,
                              end_on_exit: bool = True) -> Iterator[Step]:
        span = self.start_span(name, context, kind, attributes, links, start_time)
        with _active(span, end_on_exit=end_on_exit):
            yield span


tracer = _Tracer()


@contextmanager
def _active(span: Step, *, end_on_exit: bool = True) -> Iterator[Step]:
    """Make the step current for the block (asyncio tasks started inside inherit it); end it on the way out, with
    what went wrong."""
    token = otel_context.attach(trace.set_span_in_context(span))
    try:
        yield span
    except (asyncio.CancelledError, GeneratorExit, KeyboardInterrupt) as exc:
        span._cancelled = isinstance(exc, asyncio.CancelledError)
        raise
    except BaseException as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, f"{type(exc).__name__}: {exc}"))
        raise
    finally:
        otel_context.detach(token)
        if end_on_exit:
            span.end()


def _parent_from(parent: str | Mapping[str, Any] | None) -> SpanContext | None:
    """A carried step: a traceparent, or a mapping holding one (headers, a frame's metadata)."""
    if parent is None:
        return None
    carrier = {TRACEPARENT: parent} if isinstance(parent, str) else parent
    try:
        found = trace.get_current_span(_W3C.extract(carrier)).get_span_context()
    except (TypeError, AttributeError, ValueError):  # not a carrier at all: no parent, as when none was carried
        return None
    return found if found.is_valid else None


@contextmanager
def begin(name: str, *, parent: str | Mapping[str, Any] | None = None, story_id: str | None = None, area: str = AREA,
          level: int = logging.INFO, line: bool = True, **fields: Any) -> Iterator[Step]:
    """This process's first step of a story. It continues the step carried in `parent` (a traceparent, or a mapping
    holding one) when there is a valid one; else it starts the story `story_id` (`id_for(<message id>)`); else a new
    story, even inside another one (a worker's round is a story of its own)."""
    carried = _parent_from(parent)
    if carried is not None:
        span = Step(name, carried.trace_id, carried.span_id, area=area, level=level, line_=line, fields=fields)
    else:
        trace_id = int(id_for(story_id), 16) if story_id else _new_id(128)
        span = Step(name, trace_id, None, area=area, level=level, line_=line, fields=fields)
    with _active(span):
        yield span


@contextmanager
def step(name: str, *, area: str = AREA, level: int = logging.INFO, line: bool = True, **fields: Any) -> Iterator[Step]:
    """A timed step under the current one; outside any story, the first step of a new one."""
    current_span = trace.get_current_span()
    now = current_span.get_span_context()
    if now.is_valid:
        box = current_span._box if isinstance(current_span, Step) else None
        span = Step(name, now.trace_id, now.span_id, area=area, level=level, line_=line, fields=fields, box=box)
    else:
        span = Step(name, _new_id(128), None, area=area, level=level, line_=line, fields=fields)
    with _active(span):
        yield span


def current() -> tuple[str, str] | None:
    """(story id, step id) now, or None outside a story."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if span is INVALID_SPAN or not ctx.is_valid:
        return None
    return trace.format_trace_id(ctx.trace_id), trace.format_span_id(ctx.span_id)


def current_id() -> str | None:
    """The story id now (32 hex digits), or None outside a story."""
    found = current()
    return found[0] if found else None


def named(name: str, title: str | None = None, **fields: Any) -> Step | None:
    """Say what the current story is: a declared story's name, and this one's title ("42 checks, 1 changed"). The
    current step becomes the story's named step: its first line is written now, at INFO, and its end line goes at INFO,
    both with `story.kind`, `story.name`, `story.label` and `story.title` (and these fields), so the core lists it.
    Outside any story, or with a name nobody declared (one warning a name), nothing is named and None is returned."""
    span = trace.get_current_span()
    if not isinstance(span, Step):
        return None
    d = _declared.get(name)
    if d is None:
        if name not in _undeclared_warned:
            _undeclared_warned.add(name)
            logging.getLogger(AREA).warning("A story was named but never declared, so it isn't listed",
                                            extra={line.ATTRIBUTES: {"story.name": name}})
        return None
    marks = {"story.kind": d.kind, "story.name": d.name, "story.label": d.label, "story.title": title or d.label}
    span._fields.update(marks)
    span._fields.update(fields)
    span._level = max(span._level, logging.INFO)
    span._box["named"] = span
    logger = logging.getLogger(span._area)
    record = logger.makeRecord(span._area, logging.INFO, "(story)", 0, "%s", (f"{d.label}: {marks['story.title']}",),
                               None, extra={line.ATTRIBUTES: {**marks, **fields},
                                            line.STORY: (span.story_id, span.step_id)})
    logger.handle(record)
    return span


def retitle(title: str) -> None:
    """A better title for the current story, known only later ("42 checks, the router went down"): its end line says
    it. Nothing when the story isn't named in this process."""
    span = trace.get_current_span()
    target = span._box.get("named") if isinstance(span, Step) else None
    if target is not None:
        target._fields["story.title"] = title


def is_named() -> bool:
    """Whether the current story is named in this process: work it sets off (an automation run) is a step of a named
    story, and starts its own named one when the story it runs in isn't (a quiet timer round)."""
    span = trace.get_current_span()
    return isinstance(span, Step) and span._box.get("named") is not None


def carry() -> str | None:
    """The current step as a W3C traceparent (`00-<story id>-<step id>-01`), or None outside a story."""
    found = current()
    return f"00-{found[0]}-{found[1]}-01" if found else None


def inject(carrier: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Put the current step in a mapping (headers, a frame's metadata) under `traceparent`, when inside a story."""
    found = carry()
    if found:
        carrier[TRACEPARENT] = found
    return carrier


def as_parent(story_id: str, step_id: str | None = None) -> NonRecordingSpan:
    """A step known only by its ids, as OpenTelemetry's span (for a library that takes a parent context)."""
    return NonRecordingSpan(SpanContext(trace_id=int(story_id, 16), span_id=int(step_id, 16) if step_id else _new_id(64),
                                        is_remote=True, trace_flags=TraceFlags(TraceFlags.SAMPLED)))


line.current_story = current  # from now on, every line logged inside a step carries its ids
