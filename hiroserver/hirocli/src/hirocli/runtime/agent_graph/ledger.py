"""Graph execution ledger.

This module owns the CSV row schema, ContextVar bridge, node decorator, and
workspace sink for the per-node graph execution ledger. Rows intentionally
contain only timing, identity, usage, cost, and bounded decision metadata.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import time
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable

from hiro_commons.log import Logger

from ...domain.model_catalog import get_model_catalog

log = Logger.get("AGENT.GRAPH")

GRAPH_LEDGER_COLUMNS = [
    "ts",
    "run_id",
    "step_index",
    "node",
    "node_attempt",
    "branch_index",
    "status",
    "elapsed_ms",
    "inbound_id",
    "chat_channel_id",
    "device_id",
    "user_id",
    "character_id",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "tts_chars",
    "tts_text_tokens",
    "tts_audio_tokens",
    "stt_audio_seconds",
    "stt_audio_tokens",
    "tts_audio_seconds",
    "cost_usd",
    "pricing_version",
    "decision_kind",
    "decision_detail",
    "error_code",
    "row_kind",
    "input_preview",
    "output_preview",
]

LEDGER_LOGGER_PREFIX = "AGENT.GRAPH.LEDGER"

current_entry: ContextVar["LedgerEntry | None"] = ContextVar(
    "graph_ledger_entry",
    default=None,
)
current_run: ContextVar["RunAccumulator | None"] = ContextVar(
    "graph_ledger_run",
    default=None,
)


@dataclass(frozen=True)
class GraphLoggedSpec:
    captures: frozenset[str] = frozenset()
    flush: bool = True


def graph_logged(
    *,
    captures: Iterable[str] | None = None,
    flush: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a graph node as ledger-worthy.

    Unmarked nodes are still wrapped for ContextVar discipline but do not flush
    a parent row.
    """

    spec = GraphLoggedSpec(frozenset(captures or ()), flush=flush)

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, "_graph_logged_spec", spec)
        return fn

    return decorate


def graph_logged_spec(fn: Callable[..., Any]) -> GraphLoggedSpec | None:
    return getattr(fn, "_graph_logged_spec", None)


@dataclass
class RunAccumulator:
    """Per-turn aggregate folded from priced node rows."""

    sink: "LedgerSink"
    run_id: str
    inbound_id: str = ""
    chat_channel_id: int | str = ""
    device_id: str = ""
    user_id: str = ""
    character_id: str = ""
    started: float = field(default_factory=time.perf_counter)
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    tts_chars: int = 0
    tts_text_tokens: int = 0
    tts_audio_tokens: int = 0
    stt_audio_seconds: float = 0.0
    stt_audio_tokens: int = 0
    tts_audio_seconds: float = 0.0
    cost_usd: float = 0.0
    pricing_version: str = ""

    def fold_row(self, row: dict[str, Any]) -> None:
        if _row_kind(row) != "node" or row.get("run_id") != self.run_id:
            return

        if str(row.get("node") or "") == "call_model" and row.get("model") and not self.model:
            self.provider = str(row.get("provider") or "")
            self.model = str(row.get("model") or "")

        self.input_tokens += _to_int(row.get("input_tokens"))
        self.output_tokens += _to_int(row.get("output_tokens"))
        self.cached_input_tokens += _to_int(row.get("cached_input_tokens"))
        self.reasoning_tokens += _to_int(row.get("reasoning_tokens"))
        self.tts_chars += _to_int(row.get("tts_chars"))
        self.tts_text_tokens += _to_int(row.get("tts_text_tokens"))
        self.tts_audio_tokens += _to_int(row.get("tts_audio_tokens"))
        self.stt_audio_seconds += _to_float(row.get("stt_audio_seconds"))
        self.stt_audio_tokens += _to_int(row.get("stt_audio_tokens"))
        self.tts_audio_seconds += _to_float(row.get("tts_audio_seconds"))
        self.cost_usd += _to_float(row.get("cost_usd"))
        if row.get("pricing_version"):
            self.pricing_version = str(row.get("pricing_version") or "")

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


@dataclass
class LedgerEntry:
    sink: "LedgerSink"
    node: str
    run_id: str
    step_index: int
    node_attempt: int = 1
    branch_index: int | None = None
    inbound_id: str = ""
    chat_channel_id: int | str = ""
    device_id: str = ""
    user_id: str = ""
    character_id: str = ""
    provider: str = ""
    model: str = ""
    input_tokens: int | str = ""
    output_tokens: int | str = ""
    cached_input_tokens: int | str = ""
    reasoning_tokens: int | str = ""
    tts_chars: int | str = ""
    tts_text_tokens: int | str = ""
    tts_audio_tokens: int | str = ""
    stt_audio_seconds: float | str = ""
    stt_audio_tokens: int | str = ""
    tts_audio_seconds: float | str = ""
    decision_kind: str = ""
    decision_detail: str = ""
    input_preview: str = ""
    output_preview: str = ""
    error_code: str = ""
    captures: frozenset[str] = field(default_factory=frozenset)
    elapsed_ms: int = 0
    status: str = "ok"
    _started: float = field(default_factory=time.perf_counter)
    _children: list["LedgerEntry"] = field(default_factory=list)

    def add_usage(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cached_input_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        tts_chars: int | None = None,
        tts_text_tokens: int | None = None,
        tts_audio_tokens: int | None = None,
        stt_audio_seconds: float | None = None,
        stt_audio_tokens: int | None = None,
        tts_audio_seconds: float | None = None,
    ) -> None:
        if provider is not None:
            self.provider = provider
        if model is not None:
            self.model = model
        if input_tokens is not None:
            self.input_tokens = max(0, int(input_tokens))
        if output_tokens is not None:
            self.output_tokens = max(0, int(output_tokens))
        if cached_input_tokens is not None:
            self.cached_input_tokens = max(0, int(cached_input_tokens))
        if reasoning_tokens is not None:
            self.reasoning_tokens = max(0, int(reasoning_tokens))
        if tts_chars is not None:
            self.tts_chars = max(0, int(tts_chars))
        if tts_text_tokens is not None:
            self.tts_text_tokens = max(0, int(tts_text_tokens))
        if tts_audio_tokens is not None:
            self.tts_audio_tokens = max(0, int(tts_audio_tokens))
        if stt_audio_seconds is not None:
            self.stt_audio_seconds = max(0.0, float(stt_audio_seconds))
        if stt_audio_tokens is not None:
            self.stt_audio_tokens = max(0, int(stt_audio_tokens))
        if tts_audio_seconds is not None:
            self.tts_audio_seconds = max(0.0, float(tts_audio_seconds))

    def set_status(self, status: str) -> None:
        self.status = _slug(status) or self.status

    def set_skipped(self, code: str = "") -> None:
        self.status = "skipped"
        if code:
            self.error_code = _slug(code)

    def set_decision(self, kind: str, detail: str = "") -> None:
        self.decision_kind = _slug(kind)
        self.decision_detail = _slug(detail)

    def set_input_preview(self, value: Any) -> None:
        self.input_preview = _preview(str(value or ""))

    def set_output_preview(self, value: Any) -> None:
        self.output_preview = _preview(str(value or ""))

    def set_error(self, code: str) -> None:
        self.status = "error"
        self.error_code = _slug(code)

    def spawn_child(
        self,
        *,
        node: str,
        status: str = "ok",
        elapsed_ms: int | None = None,
        branch_index: int | None = None,
        captures: Iterable[str] | None = None,
    ) -> "LedgerEntry":
        child = LedgerEntry(
            sink=self.sink,
            node=node,
            run_id=self.run_id,
            step_index=self.sink.next_step_index(self.run_id),
            node_attempt=self.sink.next_node_attempt(self.run_id, node),
            branch_index=self.branch_index if branch_index is None else branch_index,
            inbound_id=self.inbound_id,
            chat_channel_id=self.chat_channel_id,
            device_id=self.device_id,
            user_id=self.user_id,
            character_id=self.character_id,
            captures=frozenset(captures or {"decision"}),
            status=status,
        )
        if elapsed_ms is not None:
            child.elapsed_ms = max(0, int(elapsed_ms))
        self._children.append(child)
        return child

    def finish(self, status: str, *, error_code: str = "") -> None:
        if status != "ok" or self.status == "ok":
            self.status = status
        if error_code:
            if status == "error":
                self.set_error(error_code)
            else:
                self.error_code = _slug(error_code)
        self.elapsed_ms = int((time.perf_counter() - self._started) * 1000)

    def rows(self, *, include_parent: bool) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if include_parent:
            rows.append(self.to_row())
        rows.extend(child.to_row() for child in self._children)
        return rows

    def to_row(self) -> dict[str, Any]:
        row = {
            "ts": time.time(),
            "run_id": self.run_id,
            "step_index": self.step_index,
            "node": self.node,
            "node_attempt": self.node_attempt,
            "branch_index": _blank_none(self.branch_index),
            "status": self.status,
            "row_kind": "node",
            "elapsed_ms": self.elapsed_ms,
            "inbound_id": self.inbound_id,
            "chat_channel_id": self.chat_channel_id,
            "device_id": self.device_id,
            "user_id": self.user_id,
            "character_id": self.character_id,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "tts_chars": self.tts_chars,
            "tts_text_tokens": self.tts_text_tokens,
            "tts_audio_tokens": self.tts_audio_tokens,
            "stt_audio_seconds": self.stt_audio_seconds,
            "stt_audio_tokens": self.stt_audio_tokens,
            "tts_audio_seconds": self.tts_audio_seconds,
            "decision_kind": self.decision_kind,
            "decision_detail": self.decision_detail,
            "input_preview": self.input_preview,
            "output_preview": self.output_preview,
            "error_code": self.error_code,
        }
        if "usage" not in self.captures:
            for key in (
                "provider",
                "model",
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "reasoning_tokens",
                "tts_chars",
                "tts_text_tokens",
                "tts_audio_tokens",
                "stt_audio_seconds",
                "stt_audio_tokens",
                "tts_audio_seconds",
            ):
                row[key] = ""
        if "decision" not in self.captures:
            row["decision_kind"] = ""
            row["decision_detail"] = ""
        return row


class LedgerSink:
    """Workspace-scoped writer for ``logs/graph.log``."""

    _open_lock = Lock()
    _opened: dict[Path, str] = {}
    _max_tracked_runs = 2048

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = Path(workspace_path)
        self.path = self.workspace_path / "logs" / "graph.log"
        digest = hashlib.blake2s(str(self.path).encode("utf-8"), digest_size=4).hexdigest()
        self._module = f"{LEDGER_LOGGER_PREFIX}.{digest}"
        self._logger = Logger.get(self._module)
        self._lock = Lock()
        self._step_indexes: OrderedDict[str, int] = OrderedDict()
        self._attempt_indexes: OrderedDict[tuple[str, str], int] = OrderedDict()
        with self._open_lock:
            if self.path not in self._opened:
                Logger.add_file_sink(
                    str(self.path),
                    level="INFO",
                    use_csv=True,
                    csv_columns=GRAPH_LEDGER_COLUMNS,
                    include_prefix=self._module,
                )
                self._opened[self.path] = self._module

    def next_step_index(self, run_id: str) -> int:
        key = run_id or ""
        with self._lock:
            self._touch_run(key)
            value = self._step_indexes.get(key, 0) + 1
            self._step_indexes[key] = value
            return value

    def next_node_attempt(self, run_id: str, node: str) -> int:
        run_key = run_id or ""
        key = (run_key, node or "")
        with self._lock:
            self._touch_run(run_key)
            value = self._attempt_indexes.get(key, 0) + 1
            self._attempt_indexes[key] = value
            return value

    def _touch_run(self, run_id: str) -> None:
        if run_id in self._step_indexes:
            self._step_indexes.move_to_end(run_id)
        else:
            self._step_indexes[run_id] = self._step_indexes.get(run_id, 0)
        while len(self._step_indexes) > self._max_tracked_runs:
            old_run_id, _ = self._step_indexes.popitem(last=False)
            for attempt_key in list(self._attempt_indexes):
                if attempt_key[0] == old_run_id:
                    self._attempt_indexes.pop(attempt_key, None)

    def open_entry(
        self,
        node: str,
        state: Any,
        config: Any = None,
        captures: frozenset[str] | None = None,
    ) -> LedgerEntry:
        identity = _resolve_ledger_identity(state, config)
        run_id = str(identity.get("run_id") or "").strip()
        if not run_id:
            inbound_id = str(identity.get("inbound_id") or "")
            run_id = f"chat-{inbound_id}" if inbound_id else "chat-"
        return LedgerEntry(
            sink=self,
            node=node,
            run_id=run_id,
            step_index=self.next_step_index(run_id),
            node_attempt=self.next_node_attempt(run_id, node),
            captures=frozenset(captures or ()),
            branch_index=identity.get("branch_index"),
            inbound_id=str(identity.get("inbound_id") or ""),
            chat_channel_id=identity.get("chat_channel_id") or "",
            device_id=str(identity.get("device_id") or ""),
            user_id=str(identity.get("user_id") or ""),
            character_id=str(identity.get("character_id") or ""),
        )

    def write_rows(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            priced = self._with_cost(row) if _row_kind(row) == "node" else row
            accumulator = current_run.get()
            if accumulator is not None:
                accumulator.fold_row(priced)
            payload = {column: priced.get(column, "") for column in GRAPH_LEDGER_COLUMNS}
            self._logger.info("graph_ledger", **payload)

    def write_run_row(
        self,
        accumulator: RunAccumulator,
        *,
        status: str,
        error_code: str = "",
        decision_kind: str = "",
        decision_detail: str = "",
        input_preview: str = "",
        output_preview: str = "",
    ) -> None:
        self.write_rows(
            [
                {
                    "ts": time.time(),
                    "run_id": accumulator.run_id,
                    "step_index": "",
                    "node": "@run",
                    "node_attempt": "",
                    "branch_index": "",
                    "status": _slug(status),
                    "row_kind": "run",
                    "elapsed_ms": accumulator.elapsed_ms,
                    "inbound_id": accumulator.inbound_id,
                    "chat_channel_id": accumulator.chat_channel_id,
                    "device_id": accumulator.device_id,
                    "user_id": accumulator.user_id,
                    "character_id": accumulator.character_id,
                    "provider": accumulator.provider,
                    "model": accumulator.model,
                    "input_tokens": accumulator.input_tokens or "",
                    "output_tokens": accumulator.output_tokens or "",
                    "cached_input_tokens": accumulator.cached_input_tokens or "",
                    "reasoning_tokens": accumulator.reasoning_tokens or "",
                    "tts_chars": accumulator.tts_chars or "",
                    "tts_text_tokens": accumulator.tts_text_tokens or "",
                    "tts_audio_tokens": accumulator.tts_audio_tokens or "",
                    "stt_audio_seconds": _blank_zero_float(accumulator.stt_audio_seconds),
                    "stt_audio_tokens": accumulator.stt_audio_tokens or "",
                    "tts_audio_seconds": _blank_zero_float(accumulator.tts_audio_seconds),
                    "cost_usd": _format_cost(accumulator.cost_usd)
                    if accumulator.cost_usd
                    else "",
                    "pricing_version": accumulator.pricing_version,
                    "decision_kind": _slug(decision_kind or status),
                    "decision_detail": _slug(decision_detail),
                    "input_preview": _preview(input_preview),
                    "output_preview": _preview(output_preview),
                    "error_code": _slug(error_code),
                }
            ]
        )

    def evict_run(self, run_id: str) -> None:
        key = run_id or ""
        with self._lock:
            self._step_indexes.pop(key, None)
            for attempt_key in list(self._attempt_indexes):
                if attempt_key[0] == key:
                    self._attempt_indexes.pop(attempt_key, None)

    def _with_cost(self, row: dict[str, Any]) -> dict[str, Any]:
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if not model:
            return {**row, "cost_usd": "", "pricing_version": ""}

        try:
            catalog = get_model_catalog()
            if row.get("tts_chars") not in ("", None):
                # ``tts_text_tokens`` is the metered text-token count parsed from provider
                # ``usage_metadata`` (Gemini TEXT modality / OpenAI text-tier counts). Falls back
                # to the local ``_estimate_text_tokens`` value that ``tts_node`` writes to
                # ``input_tokens`` so OpenAI ``gpt-4o-mini-tts`` keeps pricing without provider
                # usage metadata.
                tts_text_tokens = _to_int(row.get("tts_text_tokens")) or _to_int(
                    row.get("input_tokens")
                )
                estimate = catalog.estimate_tts_usage_cost(
                    provider_id=provider,
                    model_id=model,
                    input_characters=_to_int(row.get("tts_chars")),
                    input_text_tokens=tts_text_tokens,
                    generated_audio_seconds=_to_float(row.get("tts_audio_seconds")),
                    output_audio_tokens=_to_int(row.get("tts_audio_tokens")),
                )
            elif (
                row.get("stt_audio_seconds") not in ("", None)
                or row.get("stt_audio_tokens") not in ("", None)
            ):
                # STT pricing is not wired yet — see ``estimate_stt_usage_cost`` follow-up.
                # ``stt_audio_tokens`` / ``stt_audio_seconds`` are persisted now so future
                # repricing has all the inputs from ``docs/model_pricing.md``.
                return {**row, "cost_usd": "", "pricing_version": ""}
            else:
                estimate = catalog.estimate_token_usage_cost(
                    model_id=model,
                    input_tokens=_to_int(row.get("input_tokens")),
                    output_tokens=_to_int(row.get("output_tokens")),
                    cached_input_tokens=_to_int(row.get("cached_input_tokens")),
                )
        except Exception as exc:
            log.warning(
                "Graph ledger pricing estimate failed",
                provider=provider,
                model=model,
                error=str(exc),
            )
            return {**row, "cost_usd": "", "pricing_version": ""}

        if not estimate.pricing_available:
            detail = row.get("decision_detail") or estimate.reason or "pricing_missing"
            return {**row, "cost_usd": "", "pricing_version": "", "decision_detail": detail}
        return {
            **row,
            "cost_usd": f"{estimate.estimated_total:.10f}".rstrip("0").rstrip("."),
            "pricing_version": catalog.pricing_version,
        }


def wrap_graph_node(node_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(fn, "_is_pre_node_wrapped", False):
        return fn

    spec = graph_logged_spec(fn)
    is_async = inspect.iscoroutinefunction(fn)

    @functools.wraps(fn)
    async def async_wrapped(self, *args: Any, **kwargs: Any) -> Any:
        return await _run_wrapped_node_async(self, node_name, spec, fn, args, kwargs)

    @functools.wraps(fn)
    def sync_wrapped(self, *args: Any, **kwargs: Any) -> Any:
        return _run_wrapped_node_sync(self, node_name, spec, fn, args, kwargs)

    wrapped = async_wrapped if is_async else sync_wrapped
    setattr(wrapped, "_is_pre_node_wrapped", True)
    setattr(wrapped, "_graph_logged_spec", spec)
    return wrapped


def wrap_graph_callable(owner: Any, node_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a dynamically-created node callable that is not a bound method."""
    if getattr(fn, "_is_pre_node_wrapped", False):
        return fn

    spec = graph_logged_spec(fn)
    is_async = inspect.iscoroutinefunction(fn)

    @functools.wraps(fn)
    async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
        return await _run_wrapped_plain_async(owner, node_name, spec, fn, args, kwargs)

    @functools.wraps(fn)
    def sync_wrapped(*args: Any, **kwargs: Any) -> Any:
        return _run_wrapped_plain_sync(owner, node_name, spec, fn, args, kwargs)

    wrapped = async_wrapped if is_async else sync_wrapped
    setattr(wrapped, "_is_pre_node_wrapped", True)
    setattr(wrapped, "_graph_logged_spec", spec)
    return wrapped


async def _run_wrapped_plain_async(
    owner: Any,
    node_name: str,
    spec: GraphLoggedSpec | None,
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    sink: LedgerSink | None = getattr(owner, "_ledger_sink", None)
    if sink is None:
        return await fn(*args, **kwargs)

    state = args[0] if args else kwargs.get("state") or kwargs.get("sub_state") or {}
    entry = sink.open_entry(
        node_name,
        state,
        _runnable_config_from_call(args, kwargs),
        captures=spec.captures if spec is not None else None,
    )
    token = current_entry.set(entry)
    try:
        result = await fn(*args, **kwargs)
    except asyncio.CancelledError:
        entry.finish("cancelled", error_code="cancelled")
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        raise
    except Exception as exc:
        entry.finish("error", error_code=_error_code(exc))
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        raise
    else:
        entry.finish("ok")
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        return result
    finally:
        current_entry.reset(token)


def _run_wrapped_plain_sync(
    owner: Any,
    node_name: str,
    spec: GraphLoggedSpec | None,
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    sink: LedgerSink | None = getattr(owner, "_ledger_sink", None)
    if sink is None:
        return fn(*args, **kwargs)

    state = args[0] if args else kwargs.get("state") or kwargs.get("sub_state") or {}
    entry = sink.open_entry(
        node_name,
        state,
        _runnable_config_from_call(args, kwargs),
        captures=spec.captures if spec is not None else None,
    )
    token = current_entry.set(entry)
    try:
        result = fn(*args, **kwargs)
    except asyncio.CancelledError:
        entry.finish("cancelled", error_code="cancelled")
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        raise
    except Exception as exc:
        entry.finish("error", error_code=_error_code(exc))
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        raise
    else:
        entry.finish("ok")
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        return result
    finally:
        current_entry.reset(token)


async def _run_wrapped_node_async(
    self: Any,
    node_name: str,
    spec: GraphLoggedSpec | None,
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    sink: LedgerSink | None = getattr(self, "_ledger_sink", None)
    if sink is None:
        return await fn(self, *args, **kwargs)

    state = args[0] if args else kwargs.get("state") or kwargs.get("sub_state") or {}
    entry = sink.open_entry(
        node_name,
        state,
        _runnable_config_from_call(args, kwargs),
        captures=spec.captures if spec is not None else None,
    )
    token = current_entry.set(entry)
    try:
        result = await fn(self, *args, **kwargs)
    except asyncio.CancelledError:
        entry.finish("cancelled", error_code="cancelled")
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        raise
    except Exception as exc:
        entry.finish("error", error_code=_error_code(exc))
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        raise
    else:
        entry.finish("ok")
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        return result
    finally:
        current_entry.reset(token)


def _run_wrapped_node_sync(
    self: Any,
    node_name: str,
    spec: GraphLoggedSpec | None,
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    sink: LedgerSink | None = getattr(self, "_ledger_sink", None)
    if sink is None:
        return fn(self, *args, **kwargs)

    state = args[0] if args else kwargs.get("state") or kwargs.get("sub_state") or {}
    entry = sink.open_entry(
        node_name,
        state,
        _runnable_config_from_call(args, kwargs),
        captures=spec.captures if spec is not None else None,
    )
    token = current_entry.set(entry)
    try:
        result = fn(self, *args, **kwargs)
    except asyncio.CancelledError:
        entry.finish("cancelled", error_code="cancelled")
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        raise
    except Exception as exc:
        entry.finish("error", error_code=_error_code(exc))
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        raise
    else:
        entry.finish("ok")
        sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))
        return result
    finally:
        current_entry.reset(token)


def _runnable_config_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """LangGraph may pass RunnableConfig as kwargs['config'] or a positional arg after state."""
    config = kwargs.get("config")
    if isinstance(config, dict):
        return config
    for candidate in args[1:]:
        if not isinstance(candidate, dict):
            continue
        if any(key in candidate for key in ("configurable", "metadata", "callbacks", "run_id", "tags")):
            return candidate
    return None


def _resolve_ledger_identity(state: Any, config: Any = None) -> dict[str, Any]:
    """Merge graph state/config with the active ``current_run`` accumulator when needed.

    Standalone knowledge answer graphs set ``current_run`` but often omit ``inbound_id`` from
    state; without this fallback node rows get ``run_id=chat-`` and do not appear in inspect.
    """
    identity = _identity_from_state(state, config)
    run_id = str(identity.get("run_id") or "").strip()
    if run_id:
        return identity
    parent = current_run.get()
    if parent is None:
        return identity
    merged = dict(identity)
    merged["run_id"] = parent.run_id
    if not str(merged.get("inbound_id") or "").strip():
        merged["inbound_id"] = parent.inbound_id
    if not merged.get("chat_channel_id"):
        merged["chat_channel_id"] = parent.chat_channel_id
    if not str(merged.get("device_id") or "").strip():
        merged["device_id"] = parent.device_id
    if not str(merged.get("user_id") or "").strip():
        merged["user_id"] = parent.user_id
    if not str(merged.get("character_id") or "").strip():
        merged["character_id"] = parent.character_id
    return merged


def _identity_from_state(state: Any, config: Any = None) -> dict[str, Any]:
    data = state if isinstance(state, dict) else {}
    envelope = (
        data.get("inbound_envelope")
        if isinstance(data.get("inbound_envelope"), dict)
        else {}
    )
    routing = envelope.get("routing") if isinstance(envelope.get("routing"), dict) else {}
    routing_metadata = (
        routing.get("metadata") if isinstance(routing.get("metadata"), dict) else {}
    )
    state_metadata = (
        data.get("routing_metadata")
        if isinstance(data.get("routing_metadata"), dict)
        else {}
    )
    branch_index = ""
    if isinstance(data.get("audio_item"), dict):
        branch_index = data["audio_item"].get("item_index", "")
    elif isinstance(data.get("image_item"), dict):
        branch_index = data["image_item"].get("item_index", "")

    run_id = ""
    if isinstance(config, dict):
        configurable = config.get("configurable")
        config_metadata = config.get("metadata")
        if isinstance(config_metadata, dict):
            run_id = str(config_metadata.get("ledger_run_id") or "")
        if not run_id and isinstance(configurable, dict):
            run_id = str(configurable.get("run_id") or "")
        if not run_id:
            run_id = str(config.get("run_id") or "")

    return {
        "run_id": run_id,
        "inbound_id": data.get("inbound_id") or routing.get("id") or "",
        "chat_channel_id": data.get("chat_channel_id") or "",
        "device_id": (
            data.get("device_id")
            or routing.get("sender_id")
            or state_metadata.get("device_id")
            or routing_metadata.get("device_id")
            or ""
        ),
        "user_id": (
            data.get("user_id")
            or state_metadata.get("user_id")
            or routing_metadata.get("user_id")
            or ""
        ),
        "character_id": data.get("character_id") or "",
        "branch_index": branch_index,
    }


def _slug(value: str) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_")
    return "".join(ch for ch in raw if ch.isalnum() or ch in {"_", "-", ".", "/"})[:80]


def _error_code(exc: BaseException) -> str:
    name = exc.__class__.__name__.replace("Error", "").replace("Exception", "")
    return _slug(name or "error")


def _blank_none(value: Any) -> Any:
    return "" if value is None else value


def _blank_zero_float(value: float) -> float | str:
    return "" if value <= 0 else value


def _format_cost(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _row_kind(row: dict[str, Any]) -> str:
    return str(row.get("row_kind") or "node")


def _preview(value: str) -> str:
    compact = " ".join(str(value or "").split())
    return compact[:280]


def _to_int(value: Any) -> int:
    try:
        if value in ("", None):
            return 0
        return max(0, int(value))
    except Exception:
        return 0


def _to_float(value: Any) -> float:
    try:
        if value in ("", None):
            return 0.0
        return max(0.0, float(value))
    except Exception:
        return 0.0
