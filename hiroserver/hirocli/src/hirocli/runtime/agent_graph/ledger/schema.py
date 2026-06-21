"""Ledger CSV schema, entry/run dataclasses, and ``@graph_logged`` metadata."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable

from .helpers import blank_none, preview, row_kind, slug, to_float, to_int

if TYPE_CHECKING:
    from .sink import LedgerSink

GRAPH_LEDGER_COLUMNS = [
    "ts",
    "run_id",
    "step_index",
    "sub_step",
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


# Declared error-handling policy for a node (review §2.2). DESCRIPTIVE, not enforced by the
# wrapper — the wrapper always records + re-raises an *unhandled* exception regardless. The
# policy documents how the node body handles its OWN errors, so raise-vs-degrade is auditable
# in one column at the top of each method instead of buried in the body:
#   "raise"   — propagates exceptions on its main path (e.g. the LLM call nodes); no
#               except→return-partial branch.
#   "degrade" — catches a failing external call and returns a partial result so the turn
#               still completes (e.g. memory/knowledge/tts nodes), with a curated error_code.
#   "mixed"   — does both in one body (``embed_query``: re-raises the embed failure but
#               degrades an invalid-vector result). Kept explicit rather than mislabelled.
# NOT hoisted into the wrapper because each degrade site emits a curated ``error_code`` and a
# domain-specific partial return; a generic catch would drift the ledger and widen the scope.
ON_ERROR_VALUES = frozenset({"raise", "degrade", "mixed"})


@dataclass(frozen=True)
class GraphLoggedSpec:
    captures: frozenset[str] = frozenset()
    flush: bool = True
    on_error: str = "raise"


def graph_logged(
    *,
    captures: Iterable[str] | None = None,
    flush: bool = True,
    on_error: str = "raise",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a graph node as ledger-worthy.

    Unmarked nodes are still wrapped for ContextVar discipline but do not flush
    a parent row. ``on_error`` declares the node's error policy (see ``ON_ERROR_VALUES``);
    it is descriptive metadata, not a behavior switch.
    """

    if on_error not in ON_ERROR_VALUES:
        raise ValueError(f"on_error must be one of {sorted(ON_ERROR_VALUES)}, got {on_error!r}")
    spec = GraphLoggedSpec(frozenset(captures or ()), flush=flush, on_error=on_error)

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
        if row_kind(row) != "node" or row.get("run_id") != self.run_id:
            return

        if str(row.get("node") or "") == "call_model" and row.get("model") and not self.model:
            self.provider = str(row.get("provider") or "")
            self.model = str(row.get("model") or "")

        self.input_tokens += to_int(row.get("input_tokens"))
        self.output_tokens += to_int(row.get("output_tokens"))
        self.cached_input_tokens += to_int(row.get("cached_input_tokens"))
        self.reasoning_tokens += to_int(row.get("reasoning_tokens"))
        self.tts_chars += to_int(row.get("tts_chars"))
        self.tts_text_tokens += to_int(row.get("tts_text_tokens"))
        self.tts_audio_tokens += to_int(row.get("tts_audio_tokens"))
        self.stt_audio_seconds += to_float(row.get("stt_audio_seconds"))
        self.stt_audio_tokens += to_int(row.get("stt_audio_tokens"))
        self.tts_audio_seconds += to_float(row.get("tts_audio_seconds"))
        self.cost_usd += to_float(row.get("cost_usd"))
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
    sub_step: int | str = ""
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
        self.status = slug(status) or self.status

    def set_skipped(self, code: str = "") -> None:
        self.status = "skipped"
        if code:
            self.error_code = slug(code)

    def set_decision(self, kind: str, detail: str = "") -> None:
        self.decision_kind = slug(kind)
        self.decision_detail = slug(detail)

    def set_input_preview(self, value: Any, *, max_len: int = 280) -> None:
        self.input_preview = preview(str(value or ""), max_len=max_len)

    def set_output_preview(self, value: Any, *, max_len: int = 280) -> None:
        self.output_preview = preview(str(value or ""), max_len=max_len)

    def set_error(self, code: str) -> None:
        self.status = "error"
        self.error_code = slug(code)

    def fail(self, code: str, *, message: str = "", decision: str = "provider_error") -> None:
        if decision:
            self.set_decision(decision, code)
        self.set_error(code)
        if message:
            self.set_output_preview(f"error: {message}")

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
            step_index=self.step_index,
            sub_step=len(self._children) + 1,
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
                self.error_code = slug(error_code)
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
            "sub_step": self.sub_step,
            "node": self.node,
            "node_attempt": self.node_attempt,
            "branch_index": blank_none(self.branch_index),
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
