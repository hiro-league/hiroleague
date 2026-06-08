"""Tests for the ingest-trace model, adapter capture, and JSONL sidecar.

Pure: no Kuzu, no network. The adapter capture is exercised with a stub LangChain
model (structured output returns a canned pydantic object), and the end-to-end
engagement is exercised through ``ingest_episodes`` with a fake Graphiti client that
drives one LLM call per episode while a capture is active.
"""

from __future__ import annotations

import datetime as dt

import pytest
from graphiti_core.llm_client.config import ModelSize
from graphiti_core.prompts.models import Message
from pydantic import BaseModel

from hirocli.services.knowledge.graph.graphiti_adapters import (
    GraphitiLLMClient,
    GraphitiModelSpec,
)
from hirocli.services.knowledge.graph.ingest_trace import (
    TRACE_SCHEMA_VERSION,
    EpisodeIngestTrace,
    IngestCapture,
    build_episode_trace,
    current_ingest_capture,
    make_llm_stage,
    read_ingest_trace_sidecar,
    stage_node_for_operation,
    trace_dir,
    write_ingest_trace_sidecar,
)
from hirocli.domain.preferences import ModelTuning


# ── model + sidecar ──────────────────────────────────────────────────────────────────


class _Node:
    def __init__(self, uuid, name, *, labels=None, summary=""):
        self.uuid = uuid
        self.name = name
        self.labels = labels or ["Entity", "Person"]
        self.summary = summary


class _Edge:
    def __init__(self, uuid, fact, *, name="", episodes=None):
        self.uuid = uuid
        self.fact = fact
        self.name = name
        self.source_node_uuid = "s"
        self.target_node_uuid = "t"
        self.episodes = episodes or []
        self.valid_at = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        self.invalid_at = None
        self.expired_at = None


class _Result:
    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges


def test_stage_node_mapping() -> None:
    assert stage_node_for_operation("ExtractedEntities") == "extract_entities"
    assert stage_node_for_operation("EdgeDuplicate") == "resolve_facts"
    assert stage_node_for_operation("Mystery") == "other"


def test_build_episode_trace_projects_result_and_stages() -> None:
    capture = IngestCapture()
    capture.add_stage(
        make_llm_stage(
            operation="ExtractedEntities",
            messages=[{"role": "user", "content": "extract"}],
            output={"extracted_entities": [{"name": "Adam"}]},
            model_id="openai:gpt-x",
            elapsed_ms=12.5,
            input_tokens=100,
            output_tokens=20,
        )
    )
    result = _Result([_Node("n1", "Adam")], [_Edge("e1", "Adam works at Cedar", episodes=["c1"])])
    trace = build_episode_trace(
        capture=capture,
        chunk_id="c1",
        episode_index=1,
        total=3,
        name="doc · c1",
        text="Adam works at Cedar.",
        group_id="kb_main",
        reference_time="2024-01-01T00:00:00+00:00",
        result=result,
        invalidated_count=2,
    )
    assert isinstance(trace, EpisodeIngestTrace)
    d = trace.to_dict()
    assert d["schema_version"] == TRACE_SCHEMA_VERSION
    assert d["chunk_id"] == "c1"
    assert d["invalidated_count"] == 2
    assert d["persisted_nodes"][0]["name"] == "Adam"
    assert d["persisted_edges"][0]["fact"] == "Adam works at Cedar"
    assert d["stages"][0]["node"] == "extract_entities"
    assert d["stages"][0]["source"] == "llm"
    assert d["stages"][0]["input"][0]["content"] == "extract"
    assert d["stages"][0]["output"]["extracted_entities"][0]["name"] == "Adam"


def test_sidecar_roundtrip_keeps_step_linkage(tmp_path) -> None:
    capture = IngestCapture()
    capture.add_stage(
        make_llm_stage(
            operation="ExtractedEdges",
            messages=[{"role": "system", "content": "x"}],
            output={"edges": []},
            model_id="m",
            elapsed_ms=1.0,
            input_tokens=1,
            output_tokens=1,
        )
    )
    trace = build_episode_trace(
        capture=capture,
        chunk_id="c1",
        episode_index=2,
        total=4,
        name="n",
        text="t",
        group_id="kb_main",
        reference_time="",
        result=_Result([], []),
        invalidated_count=0,
    )
    write_ingest_trace_sidecar(tmp_path, run_id="ingest-7", step_index=5, trace=trace)

    records = read_ingest_trace_sidecar(tmp_path, "ingest-7")
    assert len(records) == 1
    rec = records[0]
    assert rec["run_id"] == "ingest-7"
    assert rec["step_index"] == 5
    assert rec["episode_index"] == 2
    assert rec["stages"][0]["node"] == "extract_facts"


def test_sidecar_appends_multiple_episodes(tmp_path) -> None:
    for step, idx in ((4, 1), (7, 2)):
        trace = build_episode_trace(
            capture=IngestCapture(),
            chunk_id=f"c{idx}",
            episode_index=idx,
            total=2,
            name="n",
            text="t",
            group_id="kb_main",
            reference_time="",
            result=_Result([], []),
            invalidated_count=0,
        )
        write_ingest_trace_sidecar(tmp_path, run_id="ingest-1", step_index=step, trace=trace)
    records = read_ingest_trace_sidecar(tmp_path, "ingest-1")
    assert [r["step_index"] for r in records] == [4, 7]
    assert [r["episode_index"] for r in records] == [1, 2]


def test_read_missing_sidecar_is_empty(tmp_path) -> None:
    assert read_ingest_trace_sidecar(tmp_path, "nope") == []


def test_read_skips_malformed_line(tmp_path) -> None:
    directory = trace_dir(tmp_path)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ingest-9.jsonl").write_text(
        '{"run_id": "ingest-9", "step_index": 1, "stages": []}\nnot-json\n', encoding="utf-8"
    )
    records = read_ingest_trace_sidecar(tmp_path, "ingest-9")
    assert len(records) == 1


# ── adapter capture ──────────────────────────────────────────────────────────────────


class ExtractedEntities(BaseModel):
    """Named to match graphiti's response model so ``operation`` maps to
    ``extract_entities`` (the adapter derives ``operation`` from ``__name__``)."""

    extracted_entities: list[str] = []


class _StubStructured:
    def __init__(self, parsed):
        self._parsed = parsed

    async def ainvoke(self, _messages):
        raw = type(
            "Raw",
            (),
            {"usage_metadata": {"input_tokens": 42, "output_tokens": 7}, "content": ""},
        )()
        return {"raw": raw, "parsed": self._parsed, "parsing_error": None}


class _StubModel:
    def __init__(self, parsed):
        self._parsed = parsed

    def with_structured_output(self, _model, include_raw=True):
        return _StubStructured(self._parsed)


def _client(parsed) -> GraphitiLLMClient:
    spec = GraphitiModelSpec(model_id="openai:gpt-x", tuning=ModelTuning())
    return GraphitiLLMClient(medium=spec, model_builder=lambda _s: _StubModel(parsed))


@pytest.mark.asyncio
async def test_adapter_records_stage_when_capture_active() -> None:
    client = _client(ExtractedEntities(extracted_entities=["Adam", "Cedar"]))
    capture = IngestCapture()
    token = current_ingest_capture.set(capture)
    try:
        out = await client._generate_response(
            [Message(role="user", content="extract entities")],
            response_model=ExtractedEntities,
            model_size=ModelSize.medium,
        )
    finally:
        current_ingest_capture.reset(token)
    assert out == {"extracted_entities": ["Adam", "Cedar"]}
    assert len(capture.stages) == 1
    stage = capture.stages[0]
    assert stage.operation == "ExtractedEntities"
    assert stage.node == "extract_entities"
    assert stage.input_tokens == 42
    assert stage.output_tokens == 7
    assert stage.input[0]["content"] == "extract entities"
    assert stage.output == {"extracted_entities": ["Adam", "Cedar"]}


@pytest.mark.asyncio
async def test_adapter_no_capture_is_noop() -> None:
    client = _client(ExtractedEntities(extracted_entities=["X"]))
    # No capture set on the ContextVar → nothing recorded, production path untouched.
    out = await client._generate_response(
        [Message(role="user", content="hi")],
        response_model=ExtractedEntities,
        model_size=ModelSize.medium,
    )
    assert out == {"extracted_entities": ["X"]}
    assert current_ingest_capture.get() is None


# ── non-LLM dedup observer (real graphiti internals + compat) ─────────────────────────


def test_dedup_observer_records_auto_merge() -> None:
    """The pass-through observer records graphiti's exact-name auto-merge as a dedup stage,
    while graphiti still performs the real resolution. Exercises the real
    ``_resolve_with_similarity`` + the compat signature guard."""
    from graphiti_core.nodes import EntityNode
    from graphiti_core.utils.maintenance import node_operations as nops
    from graphiti_core.utils.maintenance.dedup_helpers import (
        DedupResolutionState,
        _build_candidate_indexes,
    )

    from hirocli.services.knowledge.graph.graphiti_dedup_trace import install_dedup_trace

    assert install_dedup_trace() is True  # compat OK on the pinned graphiti

    existing = EntityNode(name="Adam Carter", group_id="kb_main", labels=["Entity", "Person"])
    extracted = EntityNode(name="adam carter", group_id="kb_main", labels=["Entity"])
    indexes = _build_candidate_indexes([existing])
    state = DedupResolutionState(resolved_nodes=[None], uuid_map={}, unresolved_indices=[])

    capture = IngestCapture()
    token = current_ingest_capture.set(capture)
    try:
        nops._resolve_with_similarity([extracted], indexes, state)
    finally:
        current_ingest_capture.reset(token)

    # graphiti really resolved the duplicate (exact normalized-name match) ...
    assert state.resolved_nodes[0] is not None
    assert state.uuid_map[extracted.uuid] == existing.uuid
    # ... and the observer recorded exactly one non-LLM dedup stage describing it.
    dedup = [s for s in capture.stages if s.node == "dedup_entities_auto"]
    assert len(dedup) == 1
    assert dedup[0].source == "dedup"
    assert dedup[0].input["name"] == "adam carter"
    assert dedup[0].output["merged_into"]["name"] == "Adam Carter"


def test_dedup_observer_noop_without_capture() -> None:
    """With no capture engaged the observer is transparent — graphiti resolves as usual and
    nothing is recorded."""
    from graphiti_core.nodes import EntityNode
    from graphiti_core.utils.maintenance import node_operations as nops
    from graphiti_core.utils.maintenance.dedup_helpers import (
        DedupResolutionState,
        _build_candidate_indexes,
    )

    from hirocli.services.knowledge.graph.graphiti_dedup_trace import install_dedup_trace

    install_dedup_trace()
    existing = EntityNode(name="Cedar Corp", group_id="kb_main", labels=["Entity"])
    extracted = EntityNode(name="cedar corp", group_id="kb_main", labels=["Entity"])
    indexes = _build_candidate_indexes([existing])
    state = DedupResolutionState(resolved_nodes=[None], uuid_map={}, unresolved_indices=[])

    assert current_ingest_capture.get() is None
    nops._resolve_with_similarity([extracted], indexes, state)
    # Real resolution still happened (transparent pass-through) ...
    assert state.uuid_map[extracted.uuid] == existing.uuid
