"""Unified node wrapper — one implementation for bound/free and sync/async callables."""

from __future__ import annotations

import asyncio
import functools
import inspect
from typing import Any, Callable

from .context import current_entry
from .helpers import slug
from .schema import GraphLoggedSpec, LedgerEntry, graph_logged_spec
from .sink import LedgerSink


def wrap_graph_node(node_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(fn, "_is_pre_node_wrapped", False):
        return fn

    spec = graph_logged_spec(fn)
    is_async = inspect.iscoroutinefunction(fn)

    @functools.wraps(fn)
    async def async_wrapped(self, *args: Any, **kwargs: Any) -> Any:
        return await _run_wrapped_async(self, node_name, spec, fn, args, kwargs, is_method=True)

    @functools.wraps(fn)
    def sync_wrapped(self, *args: Any, **kwargs: Any) -> Any:
        return _run_wrapped_sync(self, node_name, spec, fn, args, kwargs, is_method=True)

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
        return await _run_wrapped_async(owner, node_name, spec, fn, args, kwargs, is_method=False)

    @functools.wraps(fn)
    def sync_wrapped(*args: Any, **kwargs: Any) -> Any:
        return _run_wrapped_sync(owner, node_name, spec, fn, args, kwargs, is_method=False)

    wrapped = async_wrapped if is_async else sync_wrapped
    setattr(wrapped, "_is_pre_node_wrapped", True)
    setattr(wrapped, "_graph_logged_spec", spec)
    return wrapped


def _ledger_sink(owner: Any) -> LedgerSink | None:
    return getattr(owner, "_ledger_sink", None)


def _call_args(owner: Any, args: tuple[Any, ...], *, is_method: bool) -> tuple[Any, ...]:
    return (owner, *args) if is_method else args


def _open_wrapped_entry(
    sink: LedgerSink,
    node_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    spec: GraphLoggedSpec | None,
) -> tuple[LedgerEntry, Any]:
    state = args[0] if args else kwargs.get("state") or kwargs.get("sub_state") or {}
    entry = sink.open_entry(
        node_name,
        state,
        runnable_config_from_call(args, kwargs),
        captures=spec.captures if spec is not None else None,
    )
    token = current_entry.set(entry)
    return entry, token


# NOTE: an exception that escapes the node body is ALWAYS recorded + re-raised here,
# regardless of the node's declared ``spec.on_error``. ``on_error`` describes how the node
# body handles its OWN expected failures (curated error_code + partial return); it is not a
# wrapper-level swallow switch. An exception reaching this layer is therefore unhandled — a
# real bug or infra failure — and must propagate. See ``schema.ON_ERROR_VALUES``.
def _flush_entry(entry: LedgerEntry, sink: LedgerSink, spec: GraphLoggedSpec | None, *, status: str, exc: Exception | None = None) -> None:
    if status == "ok":
        entry.finish("ok")
    elif status == "cancelled":
        entry.finish("cancelled", error_code="cancelled")
    else:
        record_node_exception(entry, exc)
    sink.write_rows(entry.rows(include_parent=bool(spec and spec.flush)))


def _run_wrapped_sync(
    owner: Any,
    node_name: str,
    spec: GraphLoggedSpec | None,
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    is_method: bool,
) -> Any:
    sink = _ledger_sink(owner)
    call_args = _call_args(owner, args, is_method=is_method)
    if sink is None:
        return fn(*call_args, **kwargs)

    entry, token = _open_wrapped_entry(sink, node_name, args, kwargs, spec)
    try:
        result = fn(*call_args, **kwargs)
    except asyncio.CancelledError:
        _flush_entry(entry, sink, spec, status="cancelled")
        raise
    except Exception as exc:
        _flush_entry(entry, sink, spec, status="error", exc=exc)
        raise
    else:
        _flush_entry(entry, sink, spec, status="ok")
        return result
    finally:
        current_entry.reset(token)


async def _run_wrapped_async(
    owner: Any,
    node_name: str,
    spec: GraphLoggedSpec | None,
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    is_method: bool,
) -> Any:
    sink = _ledger_sink(owner)
    call_args = _call_args(owner, args, is_method=is_method)
    if sink is None:
        return await fn(*call_args, **kwargs)

    entry, token = _open_wrapped_entry(sink, node_name, args, kwargs, spec)
    try:
        result = await fn(*call_args, **kwargs)
    except asyncio.CancelledError:
        _flush_entry(entry, sink, spec, status="cancelled")
        raise
    except Exception as exc:
        _flush_entry(entry, sink, spec, status="error", exc=exc)
        raise
    else:
        _flush_entry(entry, sink, spec, status="ok")
        return result
    finally:
        current_entry.reset(token)


def runnable_config_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
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


def record_node_exception(entry: LedgerEntry, exc: Exception | None) -> None:
    entry.finish("error", error_code=error_code(exc or Exception("error")))
    if exc is not None and not entry.output_preview:
        entry.set_output_preview(f"error: {exc}")


def error_code(exc: BaseException) -> str:
    for attr in ("status_code", "http_status", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value:
            return slug(f"http_{value}")
        if isinstance(value, str) and value.strip():
            return slug(value)
    name = exc.__class__.__name__.replace("Error", "").replace("Exception", "")
    return slug(name or "error")
