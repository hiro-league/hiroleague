"""The bundled default prompts load, are non-empty, and back the preference defaults."""

from __future__ import annotations

import pytest

from hirocli.domain import preferences as p
from hirocli.domain.prompts import load_prompt

_PROMPT_NAMES = (
    "knowledge_rewrite",
    "knowledge_answering",
    "memory_eval_answer",
    "memory_eval_judge",
    "memory_eval_retrieval_agent",
    "chat_instructions",
)


@pytest.mark.parametrize("name", _PROMPT_NAMES)
def test_bundled_prompt_loads_non_empty(name: str) -> None:
    text = load_prompt(name)
    assert isinstance(text, str)
    assert text.strip(), f"{name}.md is empty"


def test_missing_prompt_fails_loudly() -> None:
    with pytest.raises(RuntimeError, match="does-not-exist.md"):
        load_prompt("does-not-exist")


def test_constants_are_backed_by_bundled_files() -> None:
    # The module constants must equal their bundled markdown so a future edit can't silently
    # diverge code from the .md source of truth.
    assert p.DEFAULT_KNOWLEDGE_REWRITE_PROMPT == load_prompt("knowledge_rewrite")
    assert p.DEFAULT_KNOWLEDGE_ANSWERING_PROMPT == load_prompt("knowledge_answering")
    assert p.DEFAULT_MEMORY_EVAL_ANSWER_PROMPT == load_prompt("memory_eval_answer")
    assert p.DEFAULT_MEMORY_EVAL_JUDGE_PROMPT == load_prompt("memory_eval_judge")
    assert p.DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT == load_prompt(
        "memory_eval_retrieval_agent"
    )
    assert p.DEFAULT_CHAT_INSTRUCTIONS == load_prompt("chat_instructions")


def test_prompt_defaults_registry_non_empty() -> None:
    assert p.PROMPT_DEFAULTS
    for path, text in p.PROMPT_DEFAULTS.items():
        assert text.strip(), f"PROMPT_DEFAULTS[{path}] is empty"
