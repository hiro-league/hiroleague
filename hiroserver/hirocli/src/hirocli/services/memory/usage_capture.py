"""LLM usage capture for mem0 calls.

Mem0's ``Memory.add`` performs internal LLM invocations (extraction,
ADD/UPDATE/DELETE decision) that the SDK does not surface back
to the caller. To attribute those tokens to the ``memory_out`` ledger row,
we attach a LangChain ``BaseCallbackHandler`` to every memory-bound chat
model and aggregate ``usage_metadata`` across all LLM calls into a
``ContextVar``-scoped accumulator.

Embedding usage is intentionally **not** captured here (Phase 2).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from hiro_commons.log import Logger
from langchain_core.callbacks import BaseCallbackHandler

log = Logger.get("SVC.MEMORY.USAGE")


@dataclass(frozen=True)
class MemoryUsage:
    """Aggregated LLM usage for one mem0 operation."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    call_count: int


@dataclass(frozen=True)
class MemoryAddResult:
    """Outcome of a single ``Mem0MemoryService.add`` call.

    ``stored_count`` reflects what mem0 actually wrote to the vector store
    (may be 0 even when ``usage.call_count > 0`` — e.g. extraction yielded no
    new facts, or mem0 silently dropped the response on a parse error).
    """

    usage: MemoryUsage | None
    stored_count: int
    stored_items: tuple[dict[str, Any], ...] = ()


@dataclass
class _UsageAccumulator:
    """Mutable token accumulator bound to the active ``memory_usage_scope``."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    call_count: int = 0
    _extras: dict[str, int] = field(default_factory=dict)

    def fold_usage(self, usage: dict[str, Any]) -> None:
        if not isinstance(usage, dict):
            return
        # ``usage_metadata`` is LangChain's normalized shape — same keys
        # whether the underlying provider is OpenAI, Anthropic, Google, or
        # Ollama. ``response_metadata.token_usage`` is provider-specific and
        # intentionally ignored.
        input_tokens = _int_token(usage.get("input_tokens"))
        if input_tokens is not None:
            self.input_tokens += input_tokens
        output_tokens = _int_token(usage.get("output_tokens"))
        if output_tokens is not None:
            self.output_tokens += output_tokens

        input_details = usage.get("input_token_details") or {}
        if isinstance(input_details, dict):
            cached = _int_token(input_details.get("cache_read"))
            if cached is not None:
                self.cached_input_tokens += cached

        output_details = usage.get("output_token_details") or {}
        if isinstance(output_details, dict):
            reasoning = _int_token(output_details.get("reasoning"))
            if reasoning is not None:
                self.reasoning_tokens += reasoning

        self.call_count += 1


_current_accumulator: ContextVar[_UsageAccumulator | None] = ContextVar(
    "memory_usage_accumulator",
    default=None,
)


@contextmanager
def memory_usage_scope() -> Iterator[_UsageAccumulator]:
    """Bind a fresh accumulator for the duration of one mem0 operation.

    The accumulator is exposed via a ContextVar so the LangChain callback
    handler (which may fire from a worker thread spawned by ``asyncio.to_thread``)
    can find it without explicit plumbing. ``asyncio.to_thread`` propagates
    the calling context via ``contextvars.copy_context``, so the accumulator
    set in the async parent is visible to the sync mem0 worker.
    """
    acc = _UsageAccumulator()
    token = _current_accumulator.set(acc)
    try:
        yield acc
    finally:
        _current_accumulator.reset(token)


class MemoryUsageCallbackHandler(BaseCallbackHandler):
    """LangChain handler that funnels usage into the active accumulator.

    Two responsibilities, intentionally fused on a single handler so we have
    exactly one hook into mem0's LLM call:

    1. Aggregate ``usage_metadata`` into the active ``_UsageAccumulator``.
    2. Normalize ``AIMessage.content`` from a list of content blocks (e.g.
       Gemini 3 / Claude thinking models return ``[{"type":"thinking",...},
       {"type":"text","text":"..."}]``) into a plain string. Mem0's
       ``LangchainLLM`` returns ``response.content`` straight to its parser,
       which then calls ``.strip()`` on it — that fails with
       ``'list' object has no attribute 'strip'`` and mem0 silently swallows
       the resulting parse error, dropping the extracted memories. Mutating
       ``message.content`` here propagates to ``invoke()``'s return value
       because the same ``AIMessage`` instance is what mem0 receives.
    """

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # noqa: D401
        acc = _current_accumulator.get()
        try:
            generations = getattr(response, "generations", None) or []
            for gen_list in generations:
                for gen in gen_list or []:
                    msg = getattr(gen, "message", None)
                    if msg is None:
                        continue
                    if acc is not None:
                        usage = getattr(msg, "usage_metadata", None)
                        if isinstance(usage, dict):
                            acc.fold_usage(usage)
                    content = getattr(msg, "content", None)
                    if isinstance(content, list):
                        msg.content = _flatten_content_blocks(content)
        except Exception as exc:
            # Callbacks must never break the host call; log and swallow.
            log.warning("memory usage callback failed", error=str(exc))


def _flatten_content_blocks(blocks: list[Any]) -> str:
    """Join LangChain content blocks into the plain text body.

    Skips ``thinking`` / ``reasoning`` blocks (their text is not the model's
    final answer and would corrupt mem0's JSON parse). Handles both the
    string-block form and the dict-block form (``{"type": "text", "text": ...}``).
    """
    parts: list[str] = []
    for blk in blocks:
        if isinstance(blk, str):
            parts.append(blk)
            continue
        if not isinstance(blk, dict):
            continue
        block_type = blk.get("type")
        if block_type in {"thinking", "reasoning"}:
            continue
        text = blk.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _int_token(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
