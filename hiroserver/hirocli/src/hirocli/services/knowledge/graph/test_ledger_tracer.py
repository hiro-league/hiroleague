"""Tests for the graphiti→Graph-Runs tracer bridge (``LedgerTracer``).

The tracer buffers only allowlisted spans (``add_episode`` / ``search.*``) into the
``current_spans`` ContextVar, and no-ops when no buffer is active so non-ledger
graphiti callers are unaffected. No graphiti, no network.
"""

from __future__ import annotations

from hirocli.services.knowledge.graph.ledger_tracer import LedgerTracer, current_spans


def test_buffers_only_allowlisted_spans() -> None:
    tracer = LedgerTracer()
    buf = []
    token = current_spans.set(buf)
    try:
        with tracer.start_span("add_episode") as s:
            s.add_attributes({"edge.invalidated_count": 2, "node.count": 3})
        with tracer.start_span("search.edge_search.rerank") as s:
            s.add_attributes({"candidate_count": 14, "reranked_count": 8})
        with tracer.start_span("llm.generate") as s:  # NOT allowlisted
            s.add_attributes({"prompt.name": "extract_edges.edge"})
        with tracer.start_span("edge.count") as s:  # attribute-only span, ignored
            s.add_attributes({"x": 1})
    finally:
        current_spans.reset(token)

    names = [r.name for r in buf]
    assert names == ["add_episode", "search.edge_search.rerank"]
    ae = buf[0]
    assert ae.attributes["edge.invalidated_count"] == 2
    assert ae.attributes["node.count"] == 3
    rerank = buf[1]
    assert rerank.attributes == {"candidate_count": 14, "reranked_count": 8}


def test_noop_without_active_buffer() -> None:
    tracer = LedgerTracer()
    # No current_spans set → the span runs but nothing is recorded, no error.
    with tracer.start_span("search") as s:
        s.add_attributes({"result.edges": 5})
    assert current_spans.get() is None


def test_records_even_on_exception() -> None:
    tracer = LedgerTracer()
    buf = []
    token = current_spans.set(buf)
    try:
        try:
            with tracer.start_span("add_episode") as s:
                s.add_attributes({"node.count": 1})
                raise ValueError("boom")
        except ValueError:
            pass
    finally:
        current_spans.reset(token)
    # The ``finally`` in start_span still records the span (timing/attrs captured).
    assert len(buf) == 1
    assert buf[0].name == "add_episode"
    assert buf[0].attributes["node.count"] == 1


def test_elapsed_is_populated() -> None:
    tracer = LedgerTracer()
    buf = []
    token = current_spans.set(buf)
    try:
        with tracer.start_span("search.embed_query_vector") as s:
            s.add_attributes({"query_vector.dimension": 1024})
    finally:
        current_spans.reset(token)
    assert buf[0].elapsed_ms >= 0.0
    assert buf[0].attributes["query_vector.dimension"] == 1024
