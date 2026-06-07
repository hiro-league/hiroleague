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
    judge_answer,
)
from hirocli.services.knowledge.eval_runner import MEMORY_EVAL_USER_ID, _memory_question
from hirocli.services.knowledge.eval_scoring import MARK_FAIL, MARK_PASS


class _FakeAI:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {"input_tokens": 7, "output_tokens": 3}


class _FakeStructured:
    def __init__(self, parsed: _JudgeOutput) -> None:
        self._parsed = parsed

    async def ainvoke(self, messages):  # noqa: ANN001
        return {"parsed": self._parsed, "raw": _FakeAI("{}")}


class _FakeModel:
    """Minimal chat model: returns a canned answer + a canned judge verdict."""

    def __init__(self, *, answer: str = "Otto.", verdict: str = "pass") -> None:
        self._answer = answer
        self._verdict = verdict

    async def ainvoke(self, messages):  # noqa: ANN001
        return _FakeAI(self._answer)

    def with_structured_output(self, schema, include_raw: bool = False):  # noqa: ANN001, ARG002
        return _FakeStructured(_JudgeOutput(verdict=self._verdict, grounded=True, reason="ok"))


@pytest.mark.asyncio
async def test_answer_from_context_returns_model_text() -> None:
    m = _FakeModel(answer="The drone is Otto.")
    ans = await answer_from_context(
        m, "fake:model", question="Which drone?", context=["Otto is the mascot drone"], sink=None
    )
    assert ans == "The drone is Otto."


@pytest.mark.asyncio
async def test_judge_maps_verdict_to_mark() -> None:
    m = _FakeModel(verdict="pass")
    v = await judge_answer(
        m, "fake:model", question="q", answer="Otto.", expected_answer="Otto.",
        must_not_contain=["Pip"], sink=None,
    )
    assert v.mark == MARK_PASS and v.grounded is True

    m_fail = _FakeModel(verdict="fail")
    v2 = await judge_answer(
        m_fail, "fake:model", question="q", answer="Pip.", expected_answer="Otto.",
        must_not_contain=["Pip"], sink=None,
    )
    assert v2.mark == MARK_FAIL


@pytest.mark.asyncio
async def test_judge_unknown_verdict_defaults_to_fail() -> None:
    v = await judge_answer(
        _FakeModel(verdict="weird"), "fake:model", question="q", answer="x",
        expected_answer="y", must_not_contain=[], sink=None,
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
        "must_not_contain": ["Pip"],
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
    assert leg["recalled"] == ["Otto is the current mascot drone"]
    assert row["gold"] == "Otto"


@pytest.mark.asyncio
async def test_memory_question_judge_off_has_answer_no_mark() -> None:
    mem = _FakeMemory(["Otto is the current mascot drone"])
    q = {"id": "q1", "question": "drone?", "expected_answer": "Otto", "must_not_contain": []}
    row = await _memory_question(
        mem, q, user_id=MEMORY_EVAL_USER_ID, character_id="helix",
        model=_FakeModel(answer="Otto."), model_id="fake:model", judge=False,
    )
    leg = row["legs"]["recall"]
    assert leg["answer"] == "Otto." and leg["mark"] == ""  # answer only, no judge mark
