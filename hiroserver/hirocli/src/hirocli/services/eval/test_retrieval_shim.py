"""Test-only shim so memory-eval tests keep a verbatim single-search recall path.

Production code always runs the agentic loop (P5). Existing runner tests still assert
``memory.search(question)`` behaviour — this shim stands in for ``_recall_via_agent`` unless a
test is marked ``@pytest.mark.retrieval_agent``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hirocli.services.memory.agent.accumulator import Accumulator
from hirocli.services.memory.agent.reduce import accumulated_item_to_recall_row, apply_reduce


async def verbatim_recall_shim(
    *,
    question: str,
    memory: Any,
    workspace_path: Path,
    retrieval_model: Any | None,
    retrieval_model_id: str = "",
    user_id: int,
    character_id: str,
    retrieval_limits: Any | None = None,
    retrieval_prompt_text: str = "",
) -> tuple[list[dict[str, Any]], list[str], Any | None]:
    del workspace_path, retrieval_model, retrieval_model_id, retrieval_limits, retrieval_prompt_text
    hits = await memory.search(
        question,
        user_id=user_id,
        character_id=character_id,
    )
    acc = Accumulator()
    acc.merge(hits, search_id=1, goal="verbatim")
    reduced = apply_reduce(acc, op="none", args={})
    recalled_rows = [accumulated_item_to_recall_row(item) for item in reduced.items]
    facts = [str(r["memory"]) for r in recalled_rows if str(r.get("memory") or "").strip()]
    return recalled_rows, facts, None


@pytest.fixture(autouse=True)
def _patch_verbatim_recall_for_legacy_tests(monkeypatch, request):  # noqa: ANN001
    if request.node.get_closest_marker("retrieval_agent"):
        return
    monkeypatch.setattr(
        "hirocli.services.eval.runner_memory._recall_via_agent",
        verbatim_recall_shim,
    )
