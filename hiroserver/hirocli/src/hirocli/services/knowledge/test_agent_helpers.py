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


def test_query_rewrite_entities_default_empty() -> None:
    """L3 — `entities` field is opt-in; existing callers that don't populate it
    must still get a clean default (used by the graph_expand node)."""
    rewrite = QueryRewrite()
    assert rewrite.entities == []


def test_query_rewrite_entities_round_trip() -> None:
    rewrite = QueryRewrite(
        standalone_query="what does my sister's husband do for work?",
        entities=["my sister", "husband"],
    )
    assert rewrite.entities == ["my sister", "husband"]


# --- build_qdrant_filter — L3 chunk_ids support --------------------------------


def test_build_qdrant_filter_chunk_ids_emits_has_id_condition() -> None:
    """L3 — when the caller passes chunk_ids in filters (set by graph_expand),
    build_qdrant_filter MUST emit a Qdrant HasIdCondition restricting matches
    to those point ids — that's the focus mechanism for the use_graph toggle."""
    from qdrant_client import models as qm

    from hirocli.services.knowledge.agent.helpers import build_qdrant_filter

    filt = build_qdrant_filter({"chunk_ids": ["c_1", "c_2", "c_3"]})
    assert filt is not None
    has_id_clauses = [c for c in (filt.must or []) if isinstance(c, qm.HasIdCondition)]
    assert len(has_id_clauses) == 1
    assert sorted(has_id_clauses[0].has_id) == ["c_1", "c_2", "c_3"]


def test_build_qdrant_filter_chunk_ids_combines_with_owner_filter() -> None:
    """chunk_ids + existing scalar filters → ANDed via must — both apply."""
    from qdrant_client import models as qm

    from hirocli.services.knowledge.agent.helpers import build_qdrant_filter

    filt = build_qdrant_filter({
        "owner_kind": "user",
        "owner_id": "42",
        "chunk_ids": ["c_x"],
    })
    assert filt is not None
    kinds = {type(c).__name__ for c in filt.must or []}
    assert "FieldCondition" in kinds  # owner_kind + owner_id
    assert "HasIdCondition" in kinds  # chunk_ids


def test_build_qdrant_filter_empty_chunk_ids_is_no_clause() -> None:
    """Empty / missing chunk_ids must NOT emit a HasIdCondition (would match nothing)."""
    from qdrant_client import models as qm

    from hirocli.services.knowledge.agent.helpers import build_qdrant_filter

    for value in ([], None):
        filt = build_qdrant_filter({"chunk_ids": value})
        if filt is None:
            continue  # acceptable: no clauses → None
        assert not any(isinstance(c, qm.HasIdCondition) for c in filt.must or [])
