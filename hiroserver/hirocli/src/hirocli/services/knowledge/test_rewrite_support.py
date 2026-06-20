"""Unit tests for knowledge query-rewrite helpers (P2c)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from hirocli.domain.preferences import ResolvedModel, WorkspacePreferences
from hirocli.services.knowledge.agent.helpers import NormalizedQuery, QueryRewrite
from hirocli.services.knowledge.agent import rewrite_support as rewrite_support_module
from hirocli.services.knowledge.agent.rewrite_support import (
    RewriteModelReady,
    RewriteModelSkip,
    dedupe_query_entities,
    parse_rewrite_result,
    resolve_rewrite_model,
    rewrite_state_update,
)


def test_resolve_rewrite_model_no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rewrite_support_module,
        "resolve_knowledge_rewrite_llm",
        lambda *_a, **_k: None,
    )
    outcome = resolve_rewrite_model(WorkspacePreferences(), Path("/tmp"), workspace_id=None)
    assert outcome == RewriteModelSkip("no_llm_configured")


def test_resolve_rewrite_model_no_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rewrite_support_module,
        "resolve_knowledge_rewrite_llm",
        lambda *_a, **_k: ResolvedModel(
            model_id="google:gemini-3-flash-preview",
            temperature=0.0,
            max_tokens=1024,
        ),
    )
    monkeypatch.setattr(
        rewrite_support_module,
        "get_model_catalog",
        lambda: type("C", (), {"get_model": lambda _s, _m: SimpleNamespace(features=[])})(),
    )
    outcome = resolve_rewrite_model(WorkspacePreferences(), Path("/tmp"), workspace_id=None)
    assert outcome == RewriteModelSkip("no_structured_output", model_id="google:gemini-3-flash-preview")


def test_resolve_rewrite_model_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rewrite_support_module,
        "resolve_knowledge_rewrite_llm",
        lambda *_a, **_k: ResolvedModel(
            model_id="google:gemini-3-flash-preview",
            temperature=0.0,
            max_tokens=1024,
        ),
    )
    monkeypatch.setattr(
        rewrite_support_module,
        "get_model_catalog",
        lambda: type(
            "C",
            (),
            {"get_model": lambda _s, _m: SimpleNamespace(features=["structured_output"])},
        )(),
    )
    outcome = resolve_rewrite_model(WorkspacePreferences(), Path("/tmp"), workspace_id=None)
    assert isinstance(outcome, RewriteModelReady)
    assert outcome.model_id == "google:gemini-3-flash-preview"


def test_parse_rewrite_result_success() -> None:
    raw = AIMessage(
        content="{}",
        usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    )
    outcome = parse_rewrite_result(
        {
            "parsed": QueryRewrite(standalone_query="rewritten", keywords=["a"]),
            "raw": raw,
        },
        model_id="google:gemini-3-flash-preview",
        inbound_id="in-1",
        chat_channel_id=7,
        estimated_input_tokens=10,
    )
    assert outcome.parsed is not None
    assert outcome.fail is None
    assert outcome.usage_payload is not None
    assert outcome.usage_payload["input_tokens"] == 3


def test_parse_rewrite_result_unparsed() -> None:
    outcome = parse_rewrite_result(
        {"parsed": None, "raw": None, "parsing_error": "bad json"},
        model_id="google:gemini-3-flash-preview",
        inbound_id="in-1",
        chat_channel_id=7,
        estimated_input_tokens=10,
    )
    assert outcome.parsed is None
    assert outcome.fail is not None
    assert outcome.fail["code"] == "rewrite_unparsed"


def test_rewrite_state_update_dedupes_entities() -> None:
    normalized = NormalizedQuery(raw="q", text="q", language="en")
    parsed = QueryRewrite(
        standalone_query="  new query  ",
        keywords=["  kw ", "kw"],
        knowledge_needed=True,
        entities=["Hiro", " Hiro ", ""],
    )
    update = rewrite_state_update(parsed, normalized)
    assert update["rewritten_query"] == "new query"
    assert update["rewrite_keywords"] == ["kw", "kw"]
    assert update["query_entities"] == ["Hiro"]


def test_dedupe_query_entities_preserves_order() -> None:
    assert dedupe_query_entities(["b", "a", "b", " c "]) == ["b", "a", "c"]
