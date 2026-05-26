from __future__ import annotations

from hirocli.services.knowledge.agent.helpers import QueryRewrite, matched_query_terms


def test_matched_query_terms_returns_shared_content_words() -> None:
    terms = matched_query_terms("Selim school years", "Selim attended a private school.")
    assert "selim" in terms
    assert "school" in terms
    # "years" is in the query but not the chunk → not matched.
    assert "years" not in terms


def test_matched_query_terms_drops_stopwords_and_short_tokens() -> None:
    terms = matched_query_terms("what is the school", "the school is here")
    assert terms == ["school"]


def test_matched_query_terms_arabic_alef_folding() -> None:
    # Query uses bare alef, chunk uses hamza-alef; normalization should still match them.
    terms = matched_query_terms("احمد", "قال أحمد في المدرسة")
    assert "احمد" in terms


def test_matched_query_terms_empty_inputs() -> None:
    assert matched_query_terms("", "anything") == []
    assert matched_query_terms("anything", "") == []


def test_query_rewrite_defaults_empty() -> None:
    rewrite = QueryRewrite()
    assert rewrite.standalone_query == ""
    assert rewrite.keywords == []


def test_query_rewrite_populates_fields() -> None:
    rewrite = QueryRewrite(standalone_query="what does the Research agent do?", keywords=["Research"])
    assert rewrite.standalone_query == "what does the Research agent do?"
    assert rewrite.keywords == ["Research"]
