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
from hirocli.services.knowledge.eval_runner import (
    MEMORY_EVAL_USER_ID,
    _memory_question,
    discover_corpuses,
    run_memory_eval,
)


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
        self.closed = False
        self._recall = recall

    async def clear_all(self, *, user_id, character_id=None) -> int:
        # Rebuild gate: run_memory_eval wipes the drawer before re-remembering.
        self.cleared += 1
        return 0

    async def add(self, content, *, user_id, run_id, character_id, metadata=None, ledger_sink=None):
        self.added.append(
            {"content": content, "user_id": user_id, "character_id": character_id, "metadata": metadata or {}}
        )
        return MemoryAddResult(usage=None, stored_count=1)

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
    )

    # Rebuild gate: remember=True wipes the drawer ONCE before re-remembering, so a
    # re-run rebuilds from scratch (no prior-run facts contaminating Graphiti dedup).
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


def test_discover_corpuses_pairs_by_stem(tmp_path) -> None:
    # Memory: <stem>.episodes.jsonl pairs with <stem>.questions.yaml; *_bak is skipped.
    (tmp_path / "trip.episodes.jsonl").write_text(
        '{"id":"e1","timestamp":"2024-01-01T00:00:00Z","body":"I went to Rome."}\n',
        encoding="utf-8",
    )
    (tmp_path / "trip.questions.yaml").write_text(
        '- {id: q1, question: "where?", expected_fragments: [Rome]}\n', encoding="utf-8"
    )
    (tmp_path / "trip.episodes_bak.jsonl").write_text("# backup\n", encoding="utf-8")

    mem = discover_corpuses(tmp_path, "memory")
    assert [c["id"] for c in mem] == ["trip"]  # the _bak file is ignored
    c = mem[0]
    assert c["corpus_path"].endswith("trip.episodes.jsonl")
    assert c["questions_path"].endswith("trip.questions.yaml")
    assert c["item_count"] == 1 and c["question_count"] == 1

    # Knowledge: a folder of .md pairs with <folder>.questions.yaml beside it.
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


@pytest.mark.asyncio
async def test_memory_question_row_shape(tmp_path) -> None:
    # No answering model in a bare tmp workspace → answer/judge are skipped (model is None);
    # the row still carries the recall leg with the recalled facts + gold.
    mem = _FakeMemory({"Where do I live now?": ["I moved to Denver", "I used to live in Boston"]})
    row = await _memory_question(mem, _QUESTIONS[1], user_id=MEMORY_EVAL_USER_ID, character_id="adam")
    assert row["track"] == "memory"
    leg = row["legs"]["recall"]
    # Recalled facts are now structured rows (the table reads metadata); the fake memory
    # yields plain ``{"memory": ...}`` hits, which pass through verbatim.
    assert leg["recalled"] == [
        {"memory": "I moved to Denver"},
        {"memory": "I used to live in Boston"},
    ]
    assert leg["mark"] == ""  # judge off (no model) → no mark
    assert row["gold"] == "Denver"  # ideal answer (judge reference / display)
