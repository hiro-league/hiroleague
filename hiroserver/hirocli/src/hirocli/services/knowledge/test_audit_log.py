"""Tests for knowledge audit log payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass

from hirocli.services.knowledge.audit_log import (
    build_answer_audit,
    build_ingest_audit,
    build_search_audit,
    log_knowledge_answer,
    log_knowledge_ingest,
    log_knowledge_search,
)


@dataclass
class _Hit:
    document_id: str
    point_id: str
    score: float
    title: str
    text: str


def test_build_search_audit_ranks_and_scores() -> None:
    hits = [
        _Hit(document_id="d1", point_id="p1", score=0.91, title="Alpha", text="first"),
        _Hit(document_id="d2", point_id="p2", score=0.42, title="Beta", text="second"),
    ]

    audit = build_search_audit(
        query="markdown evidence",
        top_k=5,
        min_score=0.1,
        filters={"owner_kind": "system"},
        hits=hits,
        elapsed_ms=33,
    )

    assert audit["operation"] == "knowledge.search"
    assert audit["params"]["top_k"] == 5
    assert audit["params"]["min_score"] == 0.1
    assert audit["params"]["filters"] == {"owner_kind": "system"}
    assert audit["results"][0] == {
        "rank": 1,
        "document_id": "d1",
        "point_id": "p1",
        "score": 0.91,
        "title": "Alpha",
        "text": "first",
    }
    assert audit["results"][1]["rank"] == 2
    assert audit["elapsed_ms"] == 33


def test_build_answer_audit_truncates_long_answer() -> None:
    long_text = "x" * 6000

    audit = build_answer_audit(
        query="why?",
        answer=long_text,
        top_k=3,
        min_score=0.0,
        filters={},
        sources=[_Hit(document_id="d1", point_id="p1", score=0.5, title="t", text="ctx")],
        model_id="openai:gpt-test",
        usage={"input_tokens": 10, "output_tokens": 5},
        elapsed_ms=120,
        no_results=False,
    )

    assert audit["operation"] == "knowledge.answer"
    assert audit["model_id"] == "openai:gpt-test"
    assert audit["no_results"] is False
    assert len(audit["answer"]) <= 4000
    assert audit["sources"][0]["document_id"] == "d1"
    assert audit["usage"]["input_tokens"] == 10


def test_build_ingest_audit_summarizes_params() -> None:
    audit = build_ingest_audit(
        job_id="job-1",
        status="completed",
        totals={"requested": 3, "ingested": 2, "skipped": 0, "failed": 1, "chunks": 17},
        errors={"/a/b.md": "boom"},
        params={
            "paths": ["/a/b.md", "/c/d.md", "/e/f.md"],
            "owner_kind": "system",
            "owner_id": "0",
            "tags": ["docs"],
            "file_concurrency": 4,
        },
        elapsed_ms=1500,
    )

    assert audit["operation"] == "knowledge.ingest"
    assert audit["job_id"] == "job-1"
    assert audit["status"] == "completed"
    assert audit["totals"]["chunks"] == 17
    assert audit["errors"] == {"/a/b.md": "boom"}
    assert audit["params"]["file_count"] == 3
    assert audit["params"]["tags"] == ["docs"]
    assert audit["params"]["file_concurrency"] == 4


def test_log_knowledge_search_emits_audit_json() -> None:
    calls: list[dict] = []

    class _Log:
        def fineinfo(self, msg: str, *args: object, **kwargs: object) -> None:
            calls.append({"msg": msg, "args": args, "kwargs": kwargs})

    audit = build_search_audit(
        query="q",
        top_k=5,
        min_score=0.0,
        filters={},
        hits=[],
        elapsed_ms=10,
    )
    log_knowledge_search(_Log(), audit)

    assert len(calls) == 1
    payload = json.loads(str(calls[0]["kwargs"]["audit_json"]))
    assert payload["operation"] == "knowledge.search"


def test_log_knowledge_answer_marks_no_results() -> None:
    calls: list[dict] = []

    class _Log:
        def fineinfo(self, msg: str, *args: object, **kwargs: object) -> None:
            calls.append({"msg": msg, "args": args})

    audit = build_answer_audit(
        query="q",
        answer="",
        top_k=5,
        min_score=0.0,
        filters={},
        sources=[],
        model_id=None,
        usage={},
        elapsed_ms=5,
        no_results=True,
    )
    log_knowledge_answer(_Log(), audit)

    assert calls[0]["args"][0] == "no_results"


def test_log_knowledge_ingest_includes_status_and_totals() -> None:
    calls: list[dict] = []

    class _Log:
        def fineinfo(self, msg: str, *args: object, **kwargs: object) -> None:
            calls.append({"msg": msg, "args": args})

    audit = build_ingest_audit(
        job_id="job-x",
        status="failed",
        totals={"ingested": 1, "chunks": 12, "failed": 1},
        errors={"/a.md": "boom"},
        params={"paths": ["/a.md", "/b.md"]},
        elapsed_ms=420,
    )
    log_knowledge_ingest(_Log(), audit)

    args = calls[0]["args"]
    assert args[0] == "job-x"
    assert args[1] == "failed"
    assert args[2] == 1
    assert args[3] == 12
