"""Tests for the mem0 LLM usage / content-normalization callback handler."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage

from hirocli.services.memory.usage_capture import (
    MemoryUsageCallbackHandler,
    _flatten_content_blocks,
    memory_usage_scope,
)


def _llm_result(messages: list[AIMessage]) -> SimpleNamespace:
    """Build a minimal LangChain ``LLMResult``-shaped object for ``on_llm_end``."""
    generations = [[SimpleNamespace(message=msg) for msg in messages]]
    return SimpleNamespace(generations=generations)


def test_flatten_content_blocks_joins_text_and_skips_thinking() -> None:
    blocks = [
        {"type": "thinking", "thinking": "internal reasoning, must not leak"},
        {"type": "text", "text": '{"memory": ['},
        {"type": "text", "text": '{"id": "0", "text": "User likes tea"}]}'},
    ]
    assert (
        _flatten_content_blocks(blocks)
        == '{"memory": [{"id": "0", "text": "User likes tea"}]}'
    )


def test_flatten_content_blocks_handles_string_blocks_and_unknown_types() -> None:
    blocks = ["plain ", {"type": "text", "text": "tail"}, {"type": "image", "url": "x"}]
    assert _flatten_content_blocks(blocks) == "plain tail"


def test_callback_normalizes_list_content_to_string_for_mem0() -> None:
    # Reproduces the Gemini 3 / thinking-model shape that broke mem0:
    # AIMessage.content arrives as a list of blocks, mem0 calls .strip() and
    # raises 'list' object has no attribute 'strip'.
    handler = MemoryUsageCallbackHandler()
    msg = AIMessage(
        content=[
            {"type": "thinking", "thinking": "let me extract facts..."},
            {"type": "text", "text": '{"memory": []}'},
        ],
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
        },
    )

    with memory_usage_scope() as acc:
        handler.on_llm_end(_llm_result([msg]))

    assert isinstance(msg.content, str)
    assert msg.content == '{"memory": []}'
    assert acc.input_tokens == 10
    assert acc.output_tokens == 4
    assert acc.call_count == 1


def test_callback_leaves_string_content_untouched() -> None:
    handler = MemoryUsageCallbackHandler()
    msg = AIMessage(content='{"memory": []}', usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7})

    with memory_usage_scope() as acc:
        handler.on_llm_end(_llm_result([msg]))

    assert msg.content == '{"memory": []}'
    assert acc.input_tokens == 5
    assert acc.call_count == 1


def test_callback_flattens_content_even_without_active_scope() -> None:
    """Even outside a ``memory_usage_scope``, list-content must be flattened
    so mem0's parser can call ``.strip()`` — otherwise the silent extraction
    drop reappears."""
    handler = MemoryUsageCallbackHandler()
    msg = AIMessage(
        content=[
            {"type": "text", "text": "hello"},
        ],
    )

    handler.on_llm_end(_llm_result([msg]))

    assert msg.content == "hello"
