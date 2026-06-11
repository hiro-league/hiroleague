"""Tests for the eval answer + LLM judge (eval_judge) and the unified memory question path.

Pure: a fake LangChain-style chat model (``ainvoke`` + ``with_structured_output``) so no real
LLM is needed. Verifies the answer-from-context call, the judge verdict→mark mapping, and that the
memory question wires answer + judge into the row's recall leg.
"""

from __future__ import annotations

import pytest

from hirocli.domain.memory import MemoryAddResult
from hirocli.services.knowledge.eval_judge import (
    _JudgeOutput,
    answer_from_context,
    format_recall_context,
    judge_answer,
)
from hirocli.services.knowledge.eval_runner import MEMORY_EVAL_USER_ID, _memory_question
from hirocli.services.knowledge.eval_scoring import MARK_FAIL, MARK_PASS


class _FakeAI:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {"input_tokens": 7, "output_tokens": 3}


class _FakeStructured:
    def __init__(self, parsed: _JudgeOutput, owner: "_FakeModel | None" = None) -> None:
        self._parsed = parsed
        self._owner = owner

    async def ainvoke(self, messages, config=None):  # noqa: ANN001
        if self._owner is not None:
            self._owner.last_messages = messages  # let tests assert on the judge prompt
        return {"parsed": self._parsed, "raw": _FakeAI("{}")}


class _FakeModel:
    """Minimal chat model: returns a canned answer + a canned judge verdict."""

    def __init__(
        self,
        *,
        answer: str = "Otto.",
        verdict: str = "pass",
        recall_sufficient: bool = True,
        evidence: str = "",
    ) -> None:
        self._answer = answer
        self._verdict = verdict
        self._recall_sufficient = recall_sufficient
        # Evidence the fake judge "quotes": the backstop only keeps recall_sufficient=True when this
        # is a real substring of the recalled context (judge_answer._evidence_supported).
        self._evidence = evidence
        # Capture the messages the judge/answer was actually invoked with (for prompt assertions).
        self.last_messages: list = []

    async def ainvoke(self, messages, config=None):  # noqa: ANN001
        self.last_messages = messages
        return _FakeAI(self._answer)

    def with_structured_output(self, schema, include_raw: bool = False):  # noqa: ANN001, ARG002
        return _FakeStructured(
            _JudgeOutput(
                verdict=self._verdict,
                grounded=True,
                reason="ok",
                recall_sufficient=self._recall_sufficient,
                evidence=self._evidence,
            ),
            owner=self,
        )


@pytest.mark.asyncio
async def test_answer_from_context_returns_model_text() -> None:
    m = _FakeModel(answer="The drone is Otto.")
    ans = await answer_from_context(
        m,
        "fake:model",
        question="Which drone?",
        context=[{"kind": "fact", "memory": "Otto is the mascot drone", "fact": "Otto is the mascot drone"}],
        sink=None,
    )
    assert ans == "The drone is Otto."


@pytest.mark.asyncio
async def test_judge_maps_verdict_to_mark() -> None:
    m = _FakeModel(verdict="pass")
    v = await judge_answer(
        m, "fake:model", question="q", answer="Otto.", expected_answer="Otto.",
        sink=None,
    )
    assert v.mark == MARK_PASS and v.grounded is True

    m_fail = _FakeModel(verdict="fail")
    v2 = await judge_answer(
        m_fail, "fake:model", question="q", answer="Pip.", expected_answer="Otto.",
        sink=None,
    )
    assert v2.mark == MARK_FAIL


@pytest.mark.asyncio
async def test_judge_unknown_verdict_defaults_to_fail() -> None:
    v = await judge_answer(
        _FakeModel(verdict="weird"), "fake:model", question="q", answer="x",
        expected_answer="y", sink=None,
    )
    assert v.mark == MARK_FAIL


class _FakeMemory:
    def __init__(self, facts: list[str]) -> None:
        self._facts = facts

    async def add(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
        return MemoryAddResult(usage=None, stored_count=1)

    async def search(self, query, **k):  # noqa: ANN001, ANN003, ARG002
        return [{"memory": f} for f in self._facts]


@pytest.mark.asyncio
async def test_memory_question_wires_answer_and_judge() -> None:
    mem = _FakeMemory(["Otto is the current mascot drone"])
    q = {
        "id": "q1",
        "question": "What is the current mascot drone?",
        "expected_answer": "Otto",
        "category": "supersession",
    }
    row = await _memory_question(
        mem,
        q,
        user_id=MEMORY_EVAL_USER_ID,
        character_id="helix",
        model=_FakeModel(answer="Otto.", verdict="pass"),
        model_id="fake:model",
        judge=True,
    )
    leg = row["legs"]["recall"]
    assert leg["answer"] == "Otto."  # the model answer (grounded in recalled facts)
    assert leg["mark"] == MARK_PASS  # judged against the ideal
    # recalled keeps structured hit dicts (temporal/source metadata), not plain strings
    assert leg["recalled"] == [{"memory": "Otto is the current mascot drone"}]
    assert row["gold"] == "Otto"


@pytest.mark.asyncio
async def test_memory_question_judge_off_has_answer_no_mark() -> None:
    mem = _FakeMemory(["Otto is the current mascot drone"])
    q = {"id": "q1", "question": "drone?", "expected_answer": "Otto"}
    row = await _memory_question(
        mem, q, user_id=MEMORY_EVAL_USER_ID, character_id="helix",
        model=_FakeModel(answer="Otto."), model_id="fake:model", judge=False,
    )
    leg = row["legs"]["recall"]
    assert leg["answer"] == "Otto." and leg["mark"] == ""  # answer only, no judge mark
    assert leg["recall_sufficient"] is True  # default when unjudged


def test_format_recall_context_sections_with_metadata_no_score() -> None:
    """Structured hits → Facts/Entities/Episodes sections with metadata; retrieval score excluded."""
    out = format_recall_context(
        [
            {
                "kind": "fact", "fact": "Adam works at Cedar Labs", "name": "WORKS_AT",
                "valid_at": "2024-08", "invalid_at": "", "superseded": False, "score": 0.91,
            },
            {"kind": "entity", "name": "Adam", "entity_type": "Person", "summary": "an engineer", "score": 0.8},
            {"kind": "episode", "memory": "I started at Cedar Labs.", "valid_at": "2024-08-12", "score": 0.7},
        ]
    )
    assert "Facts:" in out and "Entities:" in out and "Episodes:" in out
    assert "Adam works at Cedar Labs [WORKS_AT · valid 2024-08 → present]" in out
    assert "Adam (Person): an engineer" in out
    assert "[2024-08-12] I started at Cedar Labs." in out
    # The retrieval score is a ranking artifact — it must NOT leak into the prompt.
    assert "0.91" not in out and "score" not in out.lower()


def test_format_recall_context_empty_is_blank() -> None:
    assert format_recall_context([]) == ""
    assert format_recall_context(None) == ""


@pytest.mark.asyncio
async def test_judge_reports_recall_sufficient() -> None:
    """The judge surfaces recall_sufficient (recall-miss vs answering-miss); defaults true."""
    v_miss = await judge_answer(
        _FakeModel(verdict="fail", recall_sufficient=False), "fake:model",
        question="q", answer="I don't know.", expected_answer="Otto",
        context=[{"kind": "fact", "memory": "unrelated fact"}], sink=None,
    )
    assert v_miss.mark == MARK_FAIL and v_miss.recall_sufficient is False

    # recall_sufficient=True holds only when the judge quotes a real context line in `evidence`.
    v_ok = await judge_answer(
        _FakeModel(verdict="pass", evidence="Otto is the mascot"), "fake:model",
        question="q", answer="Otto.", expected_answer="Otto",
        context=[{"kind": "fact", "memory": "Otto is the mascot"}], sink=None,
    )
    assert v_ok.recall_sufficient is True

    # Backstop: a judge that CLAIMS recall_sufficient but quotes nothing in the context is overridden
    # to False (kills ungrounded sufficiency — the locomo conv-43 false positives).
    v_ungrounded = await judge_answer(
        _FakeModel(verdict="pass", recall_sufficient=True, evidence="a fact never recalled"),
        "fake:model", question="q", answer="Otto.", expected_answer="Otto",
        context=[{"kind": "fact", "memory": "Otto is the mascot"}], sink=None,
    )
    assert v_ungrounded.recall_sufficient is False


@pytest.mark.asyncio
async def test_judge_prompt_includes_recalled_context() -> None:
    """When context is passed, the judge's human prompt carries the recalled context block."""
    m = _FakeModel(verdict="pass")
    await judge_answer(
        m, "fake:model", question="drone?", answer="Otto.", expected_answer="Otto",
        context=[{"kind": "fact", "fact": "Otto is the mascot drone", "name": "IS"}], sink=None,
    )
    human = m.last_messages[-1].content
    assert "RECALLED CONTEXT" in human and "Otto is the mascot drone" in human
