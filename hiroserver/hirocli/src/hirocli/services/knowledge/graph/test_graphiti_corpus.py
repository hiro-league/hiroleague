"""Tests for the JSONL episode-corpus parser."""

from __future__ import annotations

import json

import pytest

from hirocli.services.knowledge.eval_runner import ADAM_CORPUS_FILE, load_questions
from hirocli.services.knowledge.graph.graphiti_corpus import (
    load_episodes_file,
    parse_episodes_jsonl,
)

# The memory corpus root (sibling eval-corpus repo) — adam_year.* lives there.
# Requires the eval-corpus checkout (or $HIRO_EVAL_CORPUS_DIR).
_EVAL_DIR = ADAM_CORPUS_FILE.parent


def _line(id_: str, ts: str, body: str, **extra) -> str:
    return json.dumps({"id": id_, "timestamp": ts, "body": body, **extra})


def test_parses_and_sorts_chronologically() -> None:
    text = "\n".join(
        [
            _line("e2", "2024-05-01T00:00:00Z", "May"),
            _line("e1", "2024-01-01T00:00:00Z", "Jan"),
            _line("e3", "2024-08-01T00:00:00Z", "Aug"),
        ]
    )
    eps = parse_episodes_jsonl(text)
    assert [e.chunk_id for e in eps] == ["e1", "e2", "e3"]  # sorted by timestamp
    assert eps[0].text == "Jan"
    assert eps[0].reference_time.year == 2024


def test_metadata_type_speaker_passthrough() -> None:
    text = _line(
        "m1",
        "2024-01-01T00:00:00Z",
        "Big news!",
        type="message",
        speaker="Adam",
        metadata={"document_id": "chat", "document_title": "Chat"},
    )
    ep = parse_episodes_jsonl(text)[0]
    assert ep.source == "message"
    assert ep.speaker == "Adam"
    assert ep.document_id == "chat"
    assert ep.document_title == "Chat"


def test_default_document_id() -> None:
    ep = parse_episodes_jsonl(
        _line("e1", "2024-01-01T00:00:00Z", "x"), default_document_id="adam_year"
    )[0]
    assert ep.document_id == "adam_year"


def test_skips_blank_and_comment_lines() -> None:
    text = "\n".join(["", "  ", "# a comment", _line("e1", "2024-01-01T00:00:00Z", "x")])
    assert len(parse_episodes_jsonl(text)) == 1


def test_duplicate_id_raises() -> None:
    text = "\n".join(
        [_line("e1", "2024-01-01T00:00:00Z", "a"), _line("e1", "2024-02-01T00:00:00Z", "b")]
    )
    with pytest.raises(ValueError, match="duplicate id"):
        parse_episodes_jsonl(text)


def test_missing_body_raises() -> None:
    with pytest.raises(ValueError, match="required"):
        parse_episodes_jsonl(_line("e1", "2024-01-01T00:00:00Z", ""))


def test_missing_timestamp_raises() -> None:
    with pytest.raises(ValueError, match="required"):
        parse_episodes_jsonl('{"id": "e1", "body": "x"}')


def test_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_episodes_jsonl("{not json}")


def test_bad_timestamp_raises() -> None:
    with pytest.raises(ValueError, match="bad timestamp"):
        parse_episodes_jsonl(_line("e1", "not-a-date", "x"))


def test_oversized_body_raises() -> None:
    big = "word " * 4000  # ~5000 tokens, well above CHUNK_MIN_TOKENS
    with pytest.raises(ValueError, match="too large"):
        parse_episodes_jsonl(_line("e1", "2024-01-01T00:00:00Z", big))


# ---- integrity of the shipped Adam corpus + question bank ----


def test_adam_corpus_parses_35_episodes() -> None:
    eps = load_episodes_file(_EVAL_DIR / "adam_year.episodes.jsonl")
    assert len(eps) == 35
    times = [e.reference_time for e in eps]
    assert times == sorted(times)  # chronological
    assert any(e.source == "message" for e in eps)  # at least one chat-style episode


def test_adam_questions_load_and_cover_categories() -> None:
    qs = load_questions(_EVAL_DIR / "adam_year.questions.yaml")
    assert len(qs) >= 25
    cats = {q["category"] for q in qs}
    for required in (
        "direct",
        "single_hop",
        "multi_hop",
        "causal",
        "non_existing",
        "event_recall",
        "preference_recall",
        "temporal",
        "knowledge_update",
        "open_domain",
        "misleading",
        "abstention",
    ):
        assert required in cats, f"missing category: {required}"
