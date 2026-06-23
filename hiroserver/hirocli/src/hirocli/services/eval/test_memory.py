"""Tests for the memory-eval track (docs/eval-corpus-tracks-design.md §8, Phase 1).

Pure: a fake conversation-memory facade records ``add``/``search`` calls and returns
canned recall hits — no Kuzu, no graphiti_core, no model. Verifies the runner remembers
each turn (chronologically), recalls per question, builds the recall-inspector row shape
(recalled facts + gold), and the no-gate summary.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from hirocli.domain.memory import MemoryAddResult
from hirocli.services.eval.runner import (
    MEMORY_EVAL_USER_ID,
    _memory_question,
    discover_corpuses,
    field_breakdown_rows,
    run_memory_eval,
    summarize_memory_rows,
)
from hirocli.services.memory.agent.accumulator import Accumulator
from hirocli.services.memory.agent.retrieval_agent import RetrievalResult

pytest_plugins = ["hirocli.services.eval.test_retrieval_shim"]


def _ev_row(qid: str, category: str, matched: int, total: int) -> dict:
    """A memory-track question row carrying evidence_recall, for the report-aggregation tests."""
    return {
        "id": qid,
        "category": category,
        "track": "memory",
        "legs": {"recall": {"mode": "recall", "mark": "✓", "recall_sufficient": True}},
        "evidence_recall": {"matched": matched, "total": total, "items": []},
    }


def test_field_breakdown_rows_sums_evidence_recall_per_bucket() -> None:
    """Evidence recall folds into the per-category report bucket as matched/total sums; a row
    without evidence_recall contributes nothing (stays 0/0)."""
    rows = [
        _ev_row("q1", "temporal", matched=1, total=2),
        _ev_row("q2", "temporal", matched=2, total=2),
        # No evidence_recall key → must not bump the bucket's evidence totals.
        {"id": "q3", "category": "single_hop", "legs": {"recall": {"mark": "✓"}}},
    ]
    bd = field_breakdown_rows(rows, ["recall"], field="category")
    assert (bd["temporal"]["evidence_matched"], bd["temporal"]["evidence_total"]) == (3, 4)
    assert (bd["single_hop"]["evidence_matched"], bd["single_hop"]["evidence_total"]) == (0, 0)


def test_summarize_memory_rows_carries_evidence_into_report() -> None:
    """The summary's by_category breakdown exposes the evidence sums so the report can show them."""
    rows = [
        _ev_row("q1", "temporal", matched=1, total=2),
        _ev_row("q2", "single_hop", matched=0, total=1),
    ]
    summary = summarize_memory_rows(rows, run_id="test")
    assert summary["by_category"]["temporal"]["evidence_total"] == 2
    assert summary["by_category"]["single_hop"]["evidence_matched"] == 0


def _ep(text: str, *, cid: str, speaker: str = "User", ts: str | None = None) -> SimpleNamespace:
    """A minimal episode duck — only the attrs the runner reads."""
    rt = dt.datetime.fromisoformat(ts) if ts else None
    return SimpleNamespace(text=text, chunk_id=cid, speaker=speaker, reference_time=rt)


class _FakeMemory:
    """Stand-in for an eval-scoped GraphitiConversationMemory — records calls, returns
    canned recall hits keyed by query text."""

    def __init__(self, recall: dict[str, list[str]]) -> None:
        self.added: list[dict] = []
        self.searched: list[str] = []
        self.cleared: int = 0  # times clear_all was called (rebuild-before-remember)
        self.fts_flushes: int = 0  # times flush_search_index was called (end-of-batch rebuild)
        self.rebuild_fts_flags: list[bool] = []  # the rebuild_fts arg seen on each add
        self.flush_should_fail = False  # when True, flush_search_index raises (non-fatal test)
        self.closed = False
        self._recall = recall

    async def clear_all(self, *, user_id, character_id=None) -> int:
        # Explicit clear: run_memory_eval wipes the drawer only when clear_before=True
        # (decoupled from remember, so batched builds can append without wiping).
        self.cleared += 1
        return 0

    async def add(
        self, content, *, user_id, run_id, character_id, metadata=None, ledger_sink=None, **kwargs
    ):
        # **kwargs absorbs the remember path's extra trace knobs (e.g. trace_label) so the fake
        # tracks the real facade signature without enumerating every cosmetic argument.
        self.rebuild_fts_flags.append(bool(kwargs.get("rebuild_fts", True)))
        self.added.append(
            {"content": content, "user_id": user_id, "character_id": character_id, "metadata": metadata or {}}
        )
        return MemoryAddResult(usage=None, stored_count=1)

    async def flush_search_index(self) -> None:
        # The bulk remember loop rebuilds the keyword index ONCE here (per-episode rebuild deferred).
        self.fts_flushes += 1
        if self.flush_should_fail:
            raise RuntimeError("simulated FTS checkpoint timeout")

    async def search(self, query, *, user_id, character_id, limit=None, **kwargs):
        self.searched.append(query)
        return [{"memory": f} for f in self._recall.get(query, [])]

    async def close(self) -> None:
        self.closed = True


_QUESTIONS = [
    {
        "id": "q_work",
        "category": "direct",
        "question": "Where do I work?",
        "expected_fragments": ["Brightloom"],
        "requires_graph": False,
        "expected_answer": "Brightloom",
    },
    {
        "id": "q_live",
        "category": "temporal",
        "question": "Where do I live now?",
        "expected_fragments": ["Denver"],
        "requires_graph": True,
        "expected_answer": "Denver",
    },
]


@pytest.mark.asyncio
async def test_run_memory_eval_remembers_and_recalls(tmp_path) -> None:
    episodes = [
        _ep("I started at Brightloom", cid="ep1", ts="2024-01-15T09:00:00+00:00"),
        _ep("I moved to Denver", cid="ep2", ts="2024-09-03T09:00:00+00:00"),
    ]
    recall = {
        "Where do I work?": ["I work at Brightloom"],
        "Where do I live now?": ["I moved to Denver", "I used to live in Boston"],
    }
    mem = _FakeMemory(recall)

    summary = await run_memory_eval(
        mem,
        tmp_path,
        set_id="adam",
        questions=_QUESTIONS,
        episodes=episodes,
        run_id="t1",
        remember=True,
        clear_before=True,
    )

    # Decoupled clear: clear_before=True wipes the drawer ONCE before remembering, so a
    # from-scratch rebuild starts clean (no prior-run facts contaminating Graphiti dedup).
    assert mem.cleared == 1
    # Remembered every turn through the real `add` path, under the eval sentinel user.
    assert len(mem.added) == 2
    assert {a["user_id"] for a in mem.added} == {MEMORY_EVAL_USER_ID}
    # Metadata carries timestamp / speaker / provenance id for the remember path.
    meta0 = mem.added[0]["metadata"]
    assert meta0["message_id"] == "ep1" and meta0["speaker"] == "User" and meta0["timestamp"]

    # Recalled once per question.
    assert mem.searched == ["Where do I work?", "Where do I live now?"]

    # Summary: single recall leg, NO gate, with the recall count.
    assert summary["track"] == "memory"
    assert summary["modes"] == ["recall"]
    assert summary["gate"] == "n/a"
    assert summary["remembered_turns"] == 2  # each fake add learns 1 fact
    assert summary["recalled_for"] == 2  # both questions recalled something

    # Both the remember/build (one ingest run) AND each recall (a retrieve run) are ledgered
    # into the workspace's logs/graph.log, so they show up in Graph Runs.
    graph_log = tmp_path / "logs" / "graph.log"
    assert graph_log.exists(), "eval wrote no graph ledger"
    text = graph_log.read_text(encoding="utf-8")
    assert "memory_eval_remember" in text  # the ingest run
    assert "memory_recall" in text  # the per-question retrieve runs


@pytest.mark.asyncio
async def test_run_memory_eval_remember_false_skips_add(tmp_path) -> None:
    mem = _FakeMemory({"Where do I work?": ["I work at Brightloom"]})
    summary = await run_memory_eval(
        mem,
        tmp_path,
        set_id="adam",
        questions=_QUESTIONS[:1],
        episodes=[_ep("x", cid="ep1")],
        run_id="t2",
        remember=False,  # re-run questions without re-remembering
    )
    assert mem.added == []  # nothing remembered
    assert mem.cleared == 0  # remember=False never wipes — recalls the existing drawer
    assert summary["remembered_turns"] == 0
    assert mem.searched == ["Where do I work?"]  # still recalls


@pytest.mark.asyncio
async def test_run_memory_eval_batch_appends_without_clear(tmp_path) -> None:
    # Batched build: remember a contiguous slice [offset:offset+limit] WITHOUT clearing, so
    # successive batches append to the same drawer instead of each wiping the last.
    episodes = [_ep(f"turn {i}", cid=f"ep{i}") for i in range(5)]
    mem = _FakeMemory({})
    summary = await run_memory_eval(
        mem,
        tmp_path,
        set_id="adam",
        questions=[],  # setup-only batch: build the corpus, recall nothing
        episodes=episodes,
        run_id="b1",
        remember=True,
        clear_before=False,  # append — do NOT wipe
        episode_offset=1,
        episode_limit=2,
    )
    assert mem.cleared == 0  # no wipe on an append batch
    # Only the windowed turns (index 1,2) were remembered — proving the slice is applied.
    assert [a["content"] for a in mem.added] == ["turn 1", "turn 2"]
    assert summary["remembered_turns"] == 2
    assert mem.searched == []  # no questions → no recall
    # Freeze fix: every turn deferred its Kuzu FTS rebuild, and the loop flushed the index ONCE
    # at the end (one checkpoint for the batch, not one per episode).
    assert mem.rebuild_fts_flags == [False, False]
    assert mem.fts_flushes == 1


@pytest.mark.asyncio
async def test_run_memory_eval_clear_only_batch(tmp_path) -> None:
    # A clear-only batch: wipe the drawer with neither remember nor questions (the "start fresh"
    # action before building the first range).
    mem = _FakeMemory({})
    summary = await run_memory_eval(
        mem,
        tmp_path,
        set_id="adam",
        questions=[],
        episodes=[_ep("x", cid="ep0")],
        run_id="c1",
        remember=False,
        clear_before=True,
    )
    assert mem.cleared == 1  # wiped
    assert mem.added == []  # nothing remembered
    assert summary["remembered_turns"] == 0


@pytest.mark.asyncio
async def test_run_memory_eval_records_and_resets_ingested_ranges(tmp_path) -> None:
    # The runner records each remember batch's window for the panel readout, and resets the whole
    # record in lock-step with a clear_before wipe (the agreed invariant: the range never outlives
    # the data).
    from hirocli.services.eval.store import get_eval_result_store

    episodes = [_ep(f"turn {i}", cid=f"ep{i}") for i in range(10)]
    mem = _FakeMemory({})
    common = dict(set_id="adam", questions=[], episodes=episodes, remember=True)
    # Two appended batches (no clear) → both windows recorded.
    await run_memory_eval(mem, tmp_path, run_id="r1", clear_before=False, episode_offset=0, episode_limit=5, **common)
    await run_memory_eval(mem, tmp_path, run_id="r2", clear_before=False, episode_offset=5, episode_limit=5, **common)
    store = get_eval_result_store(tmp_path)
    assert store.read_ranges("adam") == [
        {"start": 0, "count": 5, "cost_usd": 0.0},
        {"start": 5, "count": 5, "cost_usd": 0.0},
    ]

    # A clear_before batch wipes the range record FIRST, then records only its own window.
    await run_memory_eval(mem, tmp_path, run_id="r3", clear_before=True, episode_offset=0, episode_limit=3, **common)
    assert store.read_ranges("adam") == [{"start": 0, "count": 3, "cost_usd": 0.0}]


@pytest.mark.asyncio
async def test_run_memory_eval_flush_failure_is_non_fatal(tmp_path) -> None:
    # A failed end-of-batch FTS rebuild must NOT abort the run: the turns are already committed,
    # so aborting would mark a paid-for batch FAILED and skip the ingested-range record (→ a
    # re-run duplicates). The run completes; the range is recorded; the index self-heals later.
    from hirocli.services.eval.store import get_eval_result_store

    mem = _FakeMemory({})
    mem.flush_should_fail = True
    summary = await run_memory_eval(
        mem,
        tmp_path,
        set_id="adam",
        questions=[],
        episodes=[_ep("turn 0", cid="ep0"), _ep("turn 1", cid="ep1")],
        run_id="f1",
        remember=True,
        clear_before=False,
    )
    assert mem.fts_flushes == 1  # flush was attempted
    assert summary["remembered_turns"] == 2  # run did NOT abort
    # The ingested-range record still landed (it runs after the remember returns).
    assert get_eval_result_store(tmp_path).read_ranges("adam") == [
        {"start": 0, "count": 2, "cost_usd": 0.0}
    ]


def test_discover_corpuses_pairs_by_stem(tmp_path) -> None:
    # Memory is benchmark-driven: only corpuses listed under a benchmark in benchmarks.yaml are
    # discovered, in manifest order, tagged + labeled by benchmark. A bare file not in the manifest
    # ("scratch") stays hidden; a listed corpus with no file ("later") is skipped.
    (tmp_path / "trip.episodes.jsonl").write_text(
        '{"id":"e1","timestamp":"2024-01-01T00:00:00Z","body":"I went to Rome."}\n',
        encoding="utf-8",
    )
    (tmp_path / "trip.questions.yaml").write_text(
        '- {id: q1, question: "where?", expected_fragments: [Rome]}\n', encoding="utf-8"
    )
    (tmp_path / "scratch.episodes.jsonl").write_text(  # not in the manifest → hidden
        '{"id":"e1","timestamp":"2024-01-01T00:00:00Z","body":"unlisted."}\n', encoding="utf-8"
    )
    (tmp_path / "benchmarks.yaml").write_text(
        "benchmarks:\n"
        "  demo:\n"
        "    label: Demo\n"
        "    corpuses:\n"
        "      - {id: trip, label: Trip corpus}\n"
        "      - {id: later, label: Not yet}\n",  # listed but no episodes file → skipped
        encoding="utf-8",
    )

    mem = discover_corpuses(tmp_path, "memory")
    assert [c["id"] for c in mem] == ["trip"]  # scratch hidden, later skipped (no file)
    c = mem[0]
    assert c["corpus_path"].endswith("trip.episodes.jsonl")
    assert c["questions_path"].endswith("trip.questions.yaml")
    assert c["item_count"] == 1 and c["question_count"] == 1
    assert c["benchmark"] == "demo" and c["benchmark_label"] == "Demo"
    assert c["label"] == "Trip corpus"  # display name from the manifest

    # No manifest → no memory corpuses (a loud-enough signal without crashing the picker).
    nomani = tmp_path / "nomani"
    nomani.mkdir()
    (nomani / "x.episodes.jsonl").write_text("{}\n", encoding="utf-8")
    assert discover_corpuses(nomani, "memory") == []

    # Knowledge: a folder of .md pairs with <folder>.questions.yaml beside it (NOT manifest-driven).
    docs = tmp_path / "kb1"
    docs.mkdir()
    (docs / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / "kb1.questions.yaml").write_text(
        '- {id: k1, question: "hi?", expected_fragments: [hello]}\n', encoding="utf-8"
    )
    kb = discover_corpuses(tmp_path, "knowledge")
    assert [c["id"] for c in kb] == ["kb1"]
    assert kb[0]["item_count"] == 1 and kb[0]["question_count"] == 1

    # Missing folder → empty (the picker shows a hint, not an error).
    assert discover_corpuses(tmp_path / "nope", "memory") == []


# ---------------------------------------------------------------------------
# Parallel question phase (TaskGroup + Semaphore; question_concurrency cap)
# ---------------------------------------------------------------------------


class _SlowMemory(_FakeMemory):
    """A fake whose recalls sleep per-query, tracking peak in-flight searches —
    the observable for "the semaphore really capped the question phase"."""

    def __init__(self, recall: dict, delays: dict[str, float] | None = None) -> None:
        super().__init__(recall)
        self.delays = delays or {}
        self.in_flight = 0
        self.peak_in_flight = 0
        self.fail_queries: set[str] = set()  # queries whose recall raises

    async def search(self, query, *, user_id, character_id, limit=None, **kwargs):
        import asyncio

        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            if query in self.fail_queries:
                raise RuntimeError(f"recall blew up for {query!r}")
            await asyncio.sleep(self.delays.get(query, 0.01))
        finally:
            self.in_flight -= 1
        return await super().search(
            query, user_id=user_id, character_id=character_id, limit=limit, **kwargs
        )


def _capture_publishes(monkeypatch) -> list[tuple[str, dict]]:
    """Swap runner_memory._publish for a synchronous recorder (no event-bus timing in tests)."""
    from hirocli.services.eval import runner_memory as er  # run_memory_eval looks up _publish here

    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        er, "_publish", lambda bus, ws, etype, payload: captured.append((etype, dict(payload)))
    )
    return captured


_FOUR_QUESTIONS = [
    {
        "id": f"q{i}",
        "category": "direct",
        "question": f"question {i}?",
        "requires_graph": False,
        "expected_answer": f"answer {i}",
    }
    for i in range(4)
]


@pytest.mark.asyncio
async def test_parallel_questions_respect_concurrency_cap(tmp_path) -> None:
    # cap=2 over 4 questions: the two leading recalls must overlap (peak == 2), and the
    # semaphore must never admit a third (peak ≤ cap is the safety half of the assertion).
    mem = _SlowMemory({}, delays={q["question"]: 0.05 for q in _FOUR_QUESTIONS})
    summary = await run_memory_eval(
        mem,
        tmp_path,
        set_id="adam",
        questions=_FOUR_QUESTIONS,
        episodes=[],
        run_id="p1",
        remember=False,
        question_concurrency=2,
    )
    assert mem.peak_in_flight == 2
    assert summary["total_questions"] == 4
    assert sorted(mem.searched) == sorted(q["question"] for q in _FOUR_QUESTIONS)


@pytest.mark.asyncio
async def test_parallel_questions_default_is_serial(tmp_path) -> None:
    # question_concurrency defaults to 1 → behavior identical to the old serial loop
    # (recalls never overlap), keeping existing runs/comparisons unchanged.
    mem = _SlowMemory({}, delays={q["question"]: 0.02 for q in _FOUR_QUESTIONS[:3]})
    await run_memory_eval(
        mem,
        tmp_path,
        set_id="adam",
        questions=_FOUR_QUESTIONS[:3],
        episodes=[],
        run_id="p2",
        remember=False,
    )
    assert mem.peak_in_flight == 1
    # Serial also means bank order start-to-finish.
    assert mem.searched == [q["question"] for q in _FOUR_QUESTIONS[:3]]


@pytest.mark.asyncio
async def test_parallel_questions_keep_bank_index_out_of_order(tmp_path, monkeypatch) -> None:
    # q0 is slow, q1 fast, cap=2 → q1 COMPLETES first. Its event must still carry index=1
    # (slot-per-index), so the UI table / persisted rows key correctly however completion
    # interleaves.
    captured = _capture_publishes(monkeypatch)
    mem = _SlowMemory(
        {}, delays={_FOUR_QUESTIONS[0]["question"]: 0.1, _FOUR_QUESTIONS[1]["question"]: 0.01}
    )
    await run_memory_eval(
        mem,
        tmp_path,
        set_id="adam",
        questions=_FOUR_QUESTIONS[:2],
        episodes=[],
        run_id="p3",
        remember=False,
        question_concurrency=2,
    )
    rows = [p for etype, p in captured if etype.endswith("question_completed")]
    # Completion order: fast q1 first — but each event's index matches its BANK position.
    assert [r["id"] for r in rows] == ["q1", "q0"]
    assert [(r["id"], r["index"]) for r in rows] == [("q1", 1), ("q0", 0)]
    assert all(r["total"] == 2 for r in rows)


@pytest.mark.asyncio
async def test_parallel_question_failure_unwraps_and_fails_run(tmp_path, monkeypatch) -> None:
    # One question's recall raising must fail the run with the ORIGINAL exception (not
    # TaskGroup's ExceptionGroup wrapper) so the FAILED event/log carry a readable message.
    captured = _capture_publishes(monkeypatch)
    mem = _SlowMemory({}, delays={_FOUR_QUESTIONS[1]["question"]: 0.2})
    mem.fail_queries = {_FOUR_QUESTIONS[0]["question"]}
    with pytest.raises(RuntimeError) as excinfo:
        await run_memory_eval(
            mem,
            tmp_path,
            set_id="adam",
            questions=_FOUR_QUESTIONS[:2],
            episodes=[],
            run_id="p4",
            remember=False,
            question_concurrency=2,
        )
    assert not isinstance(excinfo.value, BaseExceptionGroup)
    failed = [p for etype, p in captured if etype.endswith(".failed")]
    assert len(failed) == 1 and "recall blew up" in failed[0]["error"]


@pytest.mark.asyncio
async def test_parallel_questions_honor_cooperative_cancel(tmp_path, monkeypatch) -> None:
    # The cancel route's flag (not task.cancel) must still stop the run: question tasks
    # raise the sentinel, which run_memory_eval translates back to CancelledError so the
    # route's terminal-cancel path is unchanged. No FAILED event, no question events.
    import asyncio

    from hirocli.services.eval.registry import get_eval_registry

    captured = _capture_publishes(monkeypatch)
    dummy = asyncio.create_task(asyncio.sleep(0))
    state = get_eval_registry().begin_run(
        tmp_path, "p5", corpus_source="adam", modes=["recall"], task=dummy, track="memory"
    )
    state.cancel_requested = True
    mem = _SlowMemory({})
    with pytest.raises(asyncio.CancelledError):
        await run_memory_eval(
            mem,
            tmp_path,
            set_id="adam",
            questions=_FOUR_QUESTIONS[:2],
            episodes=[],
            run_id="p5",
            remember=False,
            question_concurrency=2,
        )
    await dummy
    assert mem.searched == []  # no question ever started
    assert [e for e, _ in captured if e.endswith("question_completed")] == []
    assert [e for e, _ in captured if e.endswith(".failed")] == []  # cancelled ≠ failed


@pytest.mark.asyncio
async def test_memory_question_row_shape(tmp_path) -> None:
    # No answering model in a bare tmp workspace → answer/judge are skipped (model is None);
    # the row still carries the recall leg with the recalled facts + gold.
    mem = _FakeMemory({"Where do I live now?": ["I moved to Denver", "I used to live in Boston"]})
    row = await _memory_question(
        mem,
        _QUESTIONS[1],
        workspace_path=tmp_path,
        user_id=MEMORY_EVAL_USER_ID,
        character_id="adam",
    )
    assert row["track"] == "memory"
    leg = row["legs"]["recall"]
    # Recalled facts are now structured rows (the table reads metadata); the fake memory
    # yields plain ``{"memory": ...}`` hits, which pass through verbatim.
    assert leg["recalled"] == [
        {"memory": "I moved to Denver", "search_id": 1, "goal": "verbatim"},
        {"memory": "I used to live in Boston", "search_id": 1, "goal": "verbatim"},
    ]
    assert leg["mark"] == ""  # judge off (no model) → no mark
    assert row["gold"] == "Denver"  # ideal answer (judge reference / display)


@pytest.mark.retrieval_agent
@pytest.mark.asyncio
async def test_memory_recall_output_preview_summarizes_loop(tmp_path, monkeypatch) -> None:
    import csv

    from hirocli.runtime.agent_graph.ledger import LedgerSink

    async def _fake_run_retrieval(**kwargs):  # noqa: ANN003, ARG001
        acc = Accumulator()
        acc.merge(
            [{"kind": "fact", "uuid": "e1", "memory": "Employer is Brightloom", "valid_at": "2024-01-01"}],
            search_id=1,
            goal="work",
        )
        return RetrievalResult(
            accumulator=acc,
            answer_text="",
            transcript=[
                {"event": "tool_call", "turn": 1, "sub_queries": 2, "cumulative_agent_turns": 1},
                {"event": "sub_result", "turn": 1, "sid": 1, "returned": 4, "new": 3},
                {"event": "sub_result", "turn": 1, "sid": 2, "returned": 2, "new": 1},
                {"event": "final", "turn": 2, "cumulative_agent_turns": 2},
            ],
        )

    class _RetrievalModelStub:
        def bind_tools(self, tools):  # noqa: ANN001
            return self

    monkeypatch.setattr(
        "hirocli.services.eval.models.build_eval_retrieval_model",
        lambda _path: (_RetrievalModelStub(), "fake:model"),
    )
    monkeypatch.setattr(
        "hirocli.services.memory.agent.retrieval_agent.run_retrieval",
        _fake_run_retrieval,
    )

    sink = LedgerSink(tmp_path)
    mem = _FakeMemory({})
    await _memory_question(
        mem,
        _QUESTIONS[0],
        workspace_path=tmp_path,
        user_id=MEMORY_EVAL_USER_ID,
        character_id="adam",
        sink=sink,
        run_id="trace-run",
    )

    graph_log = tmp_path / "logs" / "graph.log"
    assert graph_log.exists()
    with graph_log.open(encoding="utf-8") as fh:
        recall_rows = [row for row in csv.DictReader(fh) if row.get("node") == "memory_recall"]
    assert len(recall_rows) == 1
    preview = recall_rows[0]["output_preview"]
    assert "searches=2" in preview
    assert "turns=2" in preview
    assert "Brightloom" in preview

    sidecar = tmp_path / "logs" / "retrieval_trace" / "agent" / "trace-run__q_work.jsonl"
    assert sidecar.exists()
    sidecar_lines = [line for line in sidecar.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(sidecar_lines) == 4


@pytest.mark.retrieval_agent
@pytest.mark.asyncio
async def test_recall_leg_invokes_retrieval_agent(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_run_retrieval(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        acc = Accumulator()
        acc.merge(
            [{"kind": "fact", "uuid": "e1", "memory": "Brightloom"}],
            search_id=1,
            goal="",
        )
        return RetrievalResult(
            accumulator=acc,
            answer_text="",
            transcript=[],
        )

    class _RetrievalModelStub:
        def bind_tools(self, tools):  # noqa: ANN001
            return self

    monkeypatch.setattr(
        "hirocli.services.eval.models.build_eval_retrieval_model",
        lambda _path: (_RetrievalModelStub(), "fake:model"),
    )
    monkeypatch.setattr(
        "hirocli.services.memory.agent.retrieval_agent.run_retrieval",
        _fake_run_retrieval,
    )
    mem = _FakeMemory({})
    row = await _memory_question(
        mem,
        _QUESTIONS[0],
        workspace_path=tmp_path,
        user_id=MEMORY_EVAL_USER_ID,
        character_id="adam",
    )

    assert captured["question"] == "Where do I work?"
    assert captured["limits"].max_agent_turns == 4
    assert isinstance(captured["prompt_text"], str) and captured["prompt_text"]
    # The retrieval model id must reach run_retrieval so its LLM usage can be priced/ledgered
    # (it was discarded before the agentic-cost fix, so memory_recall showed $0).
    assert captured["model_id"] == "fake:model"
    assert row["legs"]["recall"]["recalled"] == [
        {
            "kind": "fact",
            "uuid": "e1",
            "memory": "Brightloom",
            "search_id": 1,
            "goal": "",
        }
    ]


@pytest.mark.retrieval_agent
@pytest.mark.asyncio
async def test_recall_leg_returns_full_time_sorted_set(tmp_path, monkeypatch) -> None:
    """The recall leg hands the answerer the full deduped/time-sorted accumulator (reduce removed):
    two budget edges both survive, oldest-first."""
    async def _fake_run_retrieval(**kwargs):  # noqa: ANN003, ARG001
        acc = Accumulator()
        acc.merge(
            [
                {
                    "kind": "fact",
                    "uuid": "e1",
                    "memory": "Budget $40",
                    "fact": "Budget $40",
                    "valid_at": "2024-01-01",
                },
                {
                    "kind": "fact",
                    "uuid": "e2",
                    "memory": "Budget $50",
                    "fact": "Budget $50",
                    "valid_at": "2024-02-01",
                },
            ],
            search_id=1,
            goal="budget",
        )
        return RetrievalResult(
            accumulator=acc,
            answer_text="",
            transcript=[],
        )

    class _RetrievalModelStub:
        def bind_tools(self, tools):  # noqa: ANN001
            return self

    monkeypatch.setattr(
        "hirocli.services.eval.models.build_eval_retrieval_model",
        lambda _path: (_RetrievalModelStub(), "fake:model"),
    )
    monkeypatch.setattr(
        "hirocli.services.memory.agent.retrieval_agent.run_retrieval",
        _fake_run_retrieval,
    )
    mem = _FakeMemory({})
    row = await _memory_question(
        mem,
        _QUESTIONS[0],
        workspace_path=tmp_path,
        user_id=MEMORY_EVAL_USER_ID,
        character_id="adam",
    )

    recalled = row["legs"]["recall"]["recalled"]
    # The answerer gets the full deduped/time-sorted set — both edges, oldest-first.
    assert [r["memory"] for r in recalled] == ["Budget $40", "Budget $50"]


@pytest.mark.asyncio
async def test_eval_row_shape_unchanged(tmp_path) -> None:
    mem = _FakeMemory({"Where do I work?": ["I work at Brightloom"]})
    row = await _memory_question(
        mem,
        _QUESTIONS[0],
        workspace_path=tmp_path,
        user_id=MEMORY_EVAL_USER_ID,
        character_id="adam",
    )
    assert set(row.keys()) >= {
        "id",
        "category",
        "question",
        "track",
        "gold",
        "cost_usd",
        "legs",
        "answered_at",
    }
    leg = row["legs"]["recall"]
    assert set(leg.keys()) >= {
        "mode",
        "mark",
        "reason",
        "elapsed_ms",
        "answer",
        "answer_preview",
        "recalled",
        "recall_sufficient",
        "grounded",
        "evidence",
        "cost_usd",
    }
    assert leg["mode"] == "recall"
