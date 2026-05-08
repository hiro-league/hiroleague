from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langmem.short_term import RunningSummary

from hirocli.runtime.summarizing_agent_graph import (
    _bind_summary_token_limit,
    _has_non_system_content,
    _latest_non_system_message,
    _sanitize_summary_result,
    _text_from_content,
)


class _FakeModel:
    def bind(self, **kwargs):
        return kwargs


class _FakeGoogleModel(_FakeModel):
    pass


_FakeGoogleModel.__module__ = "langchain_google_genai.chat_models"


def test_bind_summary_token_limit_uses_google_output_token_name() -> None:
    assert _bind_summary_token_limit(_FakeGoogleModel(), 256) == {
        "max_output_tokens": 256
    }


def test_bind_summary_token_limit_uses_generic_token_name() -> None:
    assert _bind_summary_token_limit(_FakeModel(), 256) == {"max_tokens": 256}


def test_non_system_content_detection_rejects_system_only_input() -> None:
    assert not _has_non_system_content([SystemMessage(content="summary only")])


def test_non_system_content_detection_accepts_human_input() -> None:
    assert _has_non_system_content(
        [SystemMessage(content="summary"), HumanMessage(content="latest turn")]
    )


def test_latest_non_system_message_returns_latest_real_turn() -> None:
    latest = HumanMessage(content="latest turn")
    assert _latest_non_system_message(
        [HumanMessage(content="older"), SystemMessage(content="summary"), latest]
    ) is latest


def test_text_from_content_drops_google_signature_extras() -> None:
    content = [
        {
            "type": "text",
            "text": "Useful summary.",
            "extras": {"signature": "opaque-provider-metadata"},
        }
    ]
    assert _text_from_content(content) == "Useful summary."


def test_text_from_content_cleans_summary_block_repr() -> None:
    raw = (
        "Summary of the conversation so far: "
        "[{'type': 'text', 'text': 'Useful summary.', "
        "'extras': {'signature': 'opaque-provider-metadata'}}]"
    )
    assert _text_from_content(raw) == (
        "Summary of the conversation so far: Useful summary."
    )


def test_sanitize_summary_result_cleans_context_and_messages() -> None:
    running_summary = RunningSummary(
        summary=[
            {
                "type": "text",
                "text": "Useful summary.",
                "extras": {"signature": "opaque-provider-metadata"},
            }
        ],
        summarized_message_ids=set(),
        last_summarized_message_id=None,
    )
    message = SystemMessage(
        content=(
            "Summary of the conversation so far: "
            "[{'type': 'text', 'text': 'Useful summary.', "
            "'extras': {'signature': 'opaque-provider-metadata'}}]"
        )
    )
    result = {
        "context": {"running_summary": running_summary},
        "summarized_messages": [message],
    }

    _sanitize_summary_result(result)

    assert running_summary.summary == "Useful summary."
    assert message.content == "Summary of the conversation so far: Useful summary."
