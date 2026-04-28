from hirocli.runtime.agent_manager import _normalize_reply_content, _reply_content_type


def test_normalize_reply_content_keeps_plain_text() -> None:
    assert _normalize_reply_content("Hello") == "Hello"


def test_normalize_reply_content_extracts_provider_text_blocks() -> None:
    content = [
        {
            "type": "text",
            "text": "I'm sorry, I cannot help you with that.",
            "extras": {"signature": "opaque-provider-signature"},
        }
    ]

    assert _normalize_reply_content(content) == "I'm sorry, I cannot help you with that."


def test_normalize_reply_content_joins_multiple_text_blocks() -> None:
    content = [
        {"type": "text", "text": "First"},
        {"type": "non_text", "metadata": {"ignored": True}},
        {"type": "text", "text": "Second"},
    ]

    assert _normalize_reply_content(content) == "First\nSecond"


def test_reply_content_type_reports_block_count() -> None:
    assert _reply_content_type([{"type": "text", "text": "Hello"}]) == "list[1]"
