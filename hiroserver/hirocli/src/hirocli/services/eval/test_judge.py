"""Tests for the eval answer + LLM judge (eval_judge) and the unified memory question path.

Pure: a fake LangChain-style chat model (``ainvoke`` + ``with_structured_output``) so no real
LLM is needed. Verifies the answer-from-context call, the judge verdict→mark mapping, and that the
memory question wires answer + judge into the row's recall leg.
"""

from __future__ import annotations

import pytest

from hirocli.domain.memory import MemoryAddResult
from hirocli.services.eval.judge import (
    MEMORY_EVAL_ANSWER_SYSTEM_PROMPT,
    _JudgeOutput,
    _format_computed_block,
    answer_from_context,
    format_recall_context,
    judge_answer,
)
from hirocli.services.eval.runner import MEMORY_EVAL_USER_ID, _memory_question
from hirocli.services.eval.scoring import MARK_FAIL, MARK_PASS

pytest_plugins = ["hirocli.services.eval.test_retrieval_shim"]


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


def test_format_computed_block_renders_op_results() -> None:
    """The deterministic reduce result (Break-2) becomes an instruction-shaped line the answerer uses."""
    assert "distinct_count = 13" in _format_computed_block({"op": "distinct_count", "count": 13, "kind": "edge"})
    assert "date_diff = 5 days" in _format_computed_block({"op": "date_diff", "days": 5})
    kc = _format_computed_block({"op": "keep_conflicting", "affirming": 2, "negating": 1})
    assert "2 affirming" in kc and "1 negating" in kc
    # no-op / empty → no block at all
    assert _format_computed_block({"op": "none"}) == ""
    assert _format_computed_block(None) == ""
    # date_diff with a missing anchor → tells the answerer not to guess
    assert "not both found" in _format_computed_block({"op": "date_diff", "days": None})


@pytest.mark.asyncio
async def test_answer_from_context_includes_computed_block() -> None:
    """A declared reduce's computed result is rendered into the user message ahead of the elements."""
    m = _FakeModel(answer="13 movies.")
    await answer_from_context(
        m,
        "fake:model",
        question="How many unique movies?",
        context=[{"kind": "fact", "fact": "Watched Soul"}],
        sink=None,
        computed={"op": "distinct_count", "count": 13, "kind": "edge"},
    )
    human = m.last_messages[-1].content
    assert "## Computed Results" in human
    assert "distinct_count = 13" in human
    # the computed block precedes the recalled elements
    assert human.index("## Computed Results") < human.index("## Recalled Memory Elements")


@pytest.mark.asyncio
async def test_answer_from_context_message_layout() -> None:
    """System = hardcoded role; user message = instructions, then ## User Question, then
    ## Recalled Memory Elements (question BEFORE context — the conv-43 prompt rework)."""
    m = _FakeModel(answer="Otto.")
    await answer_from_context(
        m,
        "fake:model",
        question="Which drone?",
        context=[{"kind": "fact", "fact": "Otto is the mascot drone"}],
        sink=None,
        instructions="## Objective\nAnswer from elements only.",
    )
    system, human = m.last_messages[0].content, m.last_messages[-1].content
    assert system == MEMORY_EVAL_ANSWER_SYSTEM_PROMPT
    assert human.startswith("## Objective")
    assert "## User Question\nWhich drone?" in human
    assert "## Recalled Memory Elements" in human
    assert human.index("## User Question") < human.index("## Recalled Memory Elements")
    assert "Otto is the mascot drone" in human


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
async def test_memory_question_wires_answer_and_judge(tmp_path) -> None:
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
        workspace_path=tmp_path,
        user_id=MEMORY_EVAL_USER_ID,
        character_id="helix",
        # Answer + judge are SEPARATE eval models now; one fake serves each role.
        answer_model=_FakeModel(answer="Otto."),
        answer_model_id="fake:model",
        judge_model=_FakeModel(verdict="pass"),
        judge_model_id="fake:model",
        judge=True,
    )
    leg = row["legs"]["recall"]
    assert leg["answer"] == "Otto."  # the model answer (grounded in recalled facts)
    assert leg["mark"] == MARK_PASS  # judged against the ideal
    # recalled keeps structured hit dicts (temporal/source metadata), not plain strings
    assert leg["recalled"] == [
        {"memory": "Otto is the current mascot drone", "search_id": 1, "goal": "verbatim"},
    ]
    assert row["gold"] == "Otto"


@pytest.mark.asyncio
async def test_memory_question_judge_off_has_answer_no_mark(tmp_path) -> None:
    mem = _FakeMemory(["Otto is the current mascot drone"])
    q = {"id": "q1", "question": "drone?", "expected_answer": "Otto"}
    row = await _memory_question(
        mem,
        q,
        workspace_path=tmp_path,
        user_id=MEMORY_EVAL_USER_ID,
        character_id="helix",
        answer_model=_FakeModel(answer="Otto."),
        answer_model_id="fake:model",
        judge=False,
    )
    leg = row["legs"]["recall"]
    assert leg["answer"] == "Otto." and leg["mark"] == ""  # answer only, no judge mark
    assert leg["recall_sufficient"] is True  # default when unjudged


def test_format_recall_context_sections_with_metadata_no_score() -> None:
    """Structured hits → markdown Relevant Facts/Entities/Messages sections with metadata;
    retrieval score excluded."""
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
    assert "### Relevant Facts" in out
    assert "### Relevant Entities" in out
    assert "### Relevant Messages" in out
    # Default render = as-of only (until + superseded off); no stated on this fact → no leading date.
    assert "Adam works at Cedar Labs [WORKS_AT · as of: 2024-08]" in out
    assert "Adam (Person): an engineer" in out
    # A message's leading bare [DATE] is its statement date — always shown.
    assert "[2024-08-12] I started at Cedar Labs." in out
    # The retrieval score is a ranking artifact — it must NOT leak into the prompt.
    assert "0.91" not in out and "score" not in out.lower()


def test_format_recall_context_render_toggles() -> None:
    """show_* toggles gate the EVENT dates (as of / until / SUPERSEDED); the `stated` date and the
    message timestamp are always shown (the answerer's anchor — never gated)."""
    from hirocli.services.eval.judge import RecallRenderOptions

    hits = [
        {
            "kind": "fact", "fact": "Maya lives in Berlin", "name": "LIVES_IN",
            "stated": "2021-12-31", "valid_at": "2022-01-01", "invalid_at": "2024-03-01",
            "superseded": True,
        },
        {"kind": "episode", "memory": "Moved to Berlin.", "valid_at": "2022-01-01"},
    ]
    # All on → leading [stated] date + as of + until + SUPERSEDED; message keeps its leading date.
    all_on = format_recall_context(
        hits, RecallRenderOptions(show_event_time=True, show_expired_at=True, show_superseded=True)
    )
    assert (
        "[2021-12-31] Maya lives in Berlin [LIVES_IN · as of: 2022-01-01 · until: 2024-03-01 · SUPERSEDED]"
        in all_on
    )
    assert "[2022-01-01] Moved to Berlin." in all_on
    # All event-date toggles off → as of/until/SUPERSEDED drop, but the leading stated date survives
    # (not gated), and the message timestamp is still shown.
    no_dates = format_recall_context(
        hits,
        RecallRenderOptions(show_event_time=False, show_expired_at=False, show_superseded=False),
    )
    assert "[2021-12-31] Maya lives in Berlin [LIVES_IN]" in no_dates
    assert "as of" not in no_dates and "until" not in no_dates and "SUPERSEDED" not in no_dates
    assert "[2022-01-01] Moved to Berlin." in no_dates


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
    """When context is passed, the judge's human prompt carries the recalled elements block —
    AFTER the Model Answer (the verdict is Answer-vs-Ideal; elements are auxiliary)."""
    m = _FakeModel(verdict="pass")
    await judge_answer(
        m, "fake:model", question="drone?", answer="Otto.", expected_answer="Otto",
        context=[{"kind": "fact", "fact": "Otto is the mascot drone", "name": "IS"}], sink=None,
    )
    human = m.last_messages[-1].content
    assert "## Recalled Memory Elements" in human and "Otto is the mascot drone" in human
    assert "## Model Answer" in human
    assert human.index("## Model Answer") < human.index("## Recalled Memory Elements")
