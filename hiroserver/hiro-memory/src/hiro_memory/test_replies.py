"""The usage payload and token estimate for model replies."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from hiro_memory.replies import estimate_text_tokens, llm_usage_payload


def test_llm_usage_payload_uses_langchain_usage_metadata_only() -> None:
    msg = AIMessage(
        content="hi",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "input_token_details": {"cache_read": 3},
            "output_token_details": {"reasoning": 2},
        },
        response_metadata={
            "token_usage": {
                "prompt_tokens": 999,
                "completion_tokens": 999,
                "total_tokens": 1998,
            }
        },
    )

    payload = llm_usage_payload(
        msg,
        inbound_id="in-1",
        chat_channel_id=1,
        model_id="openai:gpt-test",
        estimated_input_tokens=50,
    )

    assert payload == {
        "inbound_id": "in-1",
        "chat_channel_id": 1,
        "model_id": "openai:gpt-test",
        "usage_available": True,
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
        "cached_input_tokens": 3,
        "reasoning_tokens": 2,
    }


def test_llm_usage_payload_falls_back_to_estimate_when_no_usage() -> None:
    msg = AIMessage(content="hi")

    payload = llm_usage_payload(
        msg,
        inbound_id="in-2",
        chat_channel_id=2,
        model_id="openai:gpt-test",
        estimated_input_tokens=42,
    )

    assert payload == {
        "inbound_id": "in-2",
        "chat_channel_id": 2,
        "model_id": "openai:gpt-test",
        "usage_available": False,
        "estimated_input_tokens": 42,
    }


def test_estimate_text_tokens_empty_is_zero() -> None:
    assert estimate_text_tokens("") == 0


def test_estimate_text_tokens_non_empty_ceil_len_over_four() -> None:
    assert estimate_text_tokens("abcd") == 1
    assert estimate_text_tokens("abcde") == 2
