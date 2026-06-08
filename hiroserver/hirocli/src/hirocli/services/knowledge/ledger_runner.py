"""Graph execution ledger lifecycle for knowledge answer runs."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from hirocli.runtime.agent_graph.ledger import RunAccumulator, current_run
from hirocli.runtime.agent_graph.tracing import langsmith_run_id

KNOWLEDGE_RUN_ID_PREFIX = "knowledge-"


@dataclass(frozen=True)
class KnowledgeLedgerRun:
    """Resolved ledger identity for one ``KnowledgeService.answer`` invocation."""

    run_id: str
    nested: bool
    accumulator: RunAccumulator | None
    runnable_config: dict[str, Any]


def preview_query(query: str, *, limit: int = 200) -> str:
    text = " ".join(str(query or "").split())
    if not text:
        return "query: <empty>"
    if len(text) <= limit:
        return f"query: {text}"
    return f"query: {text[: limit - 3].rstrip()}..."


def preview_answer(answer: str, *, limit: int = 200) -> str:
    text = " ".join(str(answer or "").split())
    if not text:
        return "answer: <empty>"
    if len(text) <= limit:
        return f"answer: {text}"
    return f"answer: {text[: limit - 3].rstrip()}..."


def ledger_identity_from_parent(parent: RunAccumulator) -> dict[str, Any]:
    return {
        "inbound_id": parent.inbound_id,
        "chat_channel_id": parent.chat_channel_id,
        "device_id": parent.device_id,
        "user_id": parent.user_id,
        "character_id": parent.character_id,
    }


def build_runnable_config(*, ledger_run_id: str, langsmith: bool) -> dict[str, Any]:
    config: dict[str, Any] = {
        "metadata": {"ledger_run_id": ledger_run_id},
        "configurable": {"run_id": ledger_run_id},
    }
    if langsmith:
        config["run_id"] = langsmith_run_id(ledger_run_id)
        config["run_name"] = "knowledge_answer"
        config["tags"] = ["knowledge", "answer"]
    return config


@asynccontextmanager
async def knowledge_answer_ledger(
    *,
    sink: Any,
    query: str,
) -> AsyncIterator[KnowledgeLedgerRun]:
    """Open ledger context for a knowledge answer graph run.

    When ``current_run`` is already set (chat agent tool path), node rows nest under
    the parent ``run_id`` and no aggregate ``row_kind=run`` row is written here.
    """
    parent = current_run.get()
    if parent is not None:
        run_id = parent.run_id
        yield KnowledgeLedgerRun(
            run_id=run_id,
            nested=True,
            accumulator=None,
            runnable_config=build_runnable_config(ledger_run_id=run_id, langsmith=False),
        )
        return

    run_id = f"{KNOWLEDGE_RUN_ID_PREFIX}{uuid.uuid4()}"
    accumulator = RunAccumulator(
        sink=sink,
        run_id=run_id,
        inbound_id=run_id,
    )
    token = current_run.set(accumulator)
    try:
        yield KnowledgeLedgerRun(
            run_id=run_id,
            nested=False,
            accumulator=accumulator,
            runnable_config=build_runnable_config(ledger_run_id=run_id, langsmith=True),
        )
    finally:
        current_run.reset(token)


def finalize_standalone_run(
    accumulator: RunAccumulator,
    *,
    query: str,
    answer: str,
    no_results: bool,
    status: str = "completed",
    error_code: str = "",
) -> None:
    """Write the aggregate ledger row for a standalone knowledge answer run."""
    detail = "no_results" if no_results else "knowledge_answer"
    accumulator.sink.write_run_row(
        accumulator,
        status=status,
        error_code=error_code,
        decision_kind=status,
        decision_detail=detail,
        input_preview=preview_query(query),
        output_preview=preview_answer(answer),
    )
    accumulator.sink.evict_run(accumulator.run_id)
