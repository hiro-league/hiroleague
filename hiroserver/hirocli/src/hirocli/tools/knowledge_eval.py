"""L3 prototype Tool — run the synthetic-corpus eval batch (Phase 5c).

Per the Tools Architecture rule, the eval batch is exposed as a Tool so the
same implementation backs CLI, the admin UI Eval Batch button, and any agent
that wants to programmatically benchmark.

The Tool wraps :func:`services.knowledge.eval_runner.run_eval` and publishes
``knowledge.eval.*`` Domain Events as questions complete — the admin
``/knowledge/events`` SSE route streams them so the UI table fills live
without polling.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from ..services.knowledge.eval_runner import (
    ADAM_EVAL_TAG,
    DEFAULT_CORPUS_DIR,
    DEFAULT_QUESTIONS_FILE,
    EVAL_SYNTHETIC_TAG,
    collect_synthetic_doc_ids,
    ingest_adam_corpus_via_service,
    ingest_synthetic_corpus_via_service,
    load_adam_questions,
    load_questions,
    run_eval,
)
from .knowledge import _close_if_owned, _resolve_service
from .knowledge_graph import _run_graph_ingest_for_documents
from .base import Tool, ToolParam

log = Logger.get("SVC.KNOWLEDGE.EVAL.TOOL")


class KnowledgeL3EvalRunTool(Tool):
    """Run the L3 synthetic-corpus eval batch end-to-end.

    Stages (each opt-in via params; defaults to "run questions only"):

    1. ``ingest_synthetic=True`` → ingest the eval/l3_synthetic/*.md corpus
       into the workspace's knowledge index with the ``_l3_eval_synthetic``
       tag auto-applied (so retrieval can be scoped to ONLY the eval docs).
    2. ``build_graph=True`` → run ``knowledge_graph_ingest_batch`` over the
       freshly-ingested doc_ids (or all docs carrying the eval tag if step 1
       was skipped).
    3. Always: load ``eval/l3_questions.yaml``, run each question via
       ``service.compare`` (flat ⊕ graph concurrently), score against
       ``expected_fragments``, publish ``knowledge.eval.question_completed``
       events as each completes, end with ``knowledge.eval.completed``
       carrying the gate verdict.

    Returns the aggregate summary + per-question table. The streaming SSE
    surface is what the admin UI uses; this synchronous return matches what
    a CLI/agent caller would want.
    """

    runtime = True
    name = "knowledge_l3_eval_run"
    description = (
        "L3 prototype: run the synthetic-corpus eval batch (flat vs graph "
        "side-by-side, 12 questions, PROCEED/PIVOT gate). Optionally also "
        "ingests the corpus and builds the graph first. Publishes per-question "
        "events on the knowledge event stream for live UI updates."
    )
    params = {
        "ingest_synthetic": ToolParam(
            bool,
            "Ingest eval/l3_synthetic/*.md into the workspace (auto-tagged "
            "_l3_eval_synthetic). Skip if already ingested. Default false.",
            required=False,
        ),
        "build_graph": ToolParam(
            bool,
            "Graph-ingest the synthetic docs after standard ingest. Skip if "
            "graph already built. Default false.",
            required=False,
        ),
        "corpus_source": ToolParam(
            str,
            "'synthetic' (default, the .md L3 corpus) or 'adam' (the temporal JSONL "
            "episode corpus). For 'adam', ingest_synthetic doubles as 'ingest the corpus'.",
            required=False,
        ),
        "question_ids": ToolParam(
            list[str],
            "Adam path only: run just these question ids (empty = all).",
            required=False,
        ),
        "run_id": ToolParam(
            str,
            "Correlation id for the event stream (auto-generated when blank).",
            required=False,
        ),
        "workspace": ToolParam(
            str, "Workspace name (default: registry default)", required=False
        ),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(
        self,
        ingest_synthetic: bool = False,
        build_graph: bool = False,
        corpus_source: str = "synthetic",
        question_ids: list[str] | None = None,
        run_id: str = "",
        workspace: str | None = None,
    ) -> dict[str, Any]:
        return asyncio.run(
            self.execute_async(
                ingest_synthetic=ingest_synthetic,
                build_graph=build_graph,
                corpus_source=corpus_source,
                question_ids=question_ids,
                run_id=run_id,
                workspace=workspace,
            )
        )

    async def execute_async(
        self,
        ingest_synthetic: bool = False,
        build_graph: bool = False,
        corpus_source: str = "synthetic",
        question_ids: list[str] | None = None,
        run_id: str = "",
        workspace: str | None = None,
    ) -> dict[str, Any]:
        rid = (run_id or "").strip() or f"l3eval-{uuid.uuid4()}"
        runtime = getattr(self, "_runtime", None)
        service, workspace_path, owned = _resolve_service(runtime, workspace)
        try:
            # Adam temporal corpus path. ``ingest_synthetic`` doubles as "ingest the
            # corpus" so subsets can re-run without re-ingesting; ``question_ids``
            # narrows the run to a selected subset.
            if corpus_source == "adam":
                episodes = 0
                if ingest_synthetic:
                    episodes = await ingest_adam_corpus_via_service(service, workspace_path)
                questions = load_adam_questions()
                if question_ids:
                    wanted = set(question_ids)
                    questions = [q for q in questions if q["id"] in wanted]
                summary = await run_eval(
                    service,
                    workspace_path,
                    questions=questions,
                    run_id=rid,
                    filters={"tags": [ADAM_EVAL_TAG]},
                )
                return {
                    "run_id": rid,
                    "summary": summary.to_payload(),
                    "questions": [
                        q.to_payload(index=i, total=len(summary.questions))
                        for i, q in enumerate(summary.questions)
                    ],
                    "corpus_source": "adam",
                    "episodes_ingested": episodes,
                }

            ingested_ids: list[str] = []
            if ingest_synthetic:
                log.info("⬇️ eval — ingesting synthetic corpus · run_id=%s", rid)
                ingested_ids = await ingest_synthetic_corpus_via_service(
                    service, workspace_path
                )

            if build_graph:
                doc_ids = ingested_ids or await collect_synthetic_doc_ids(service)
                if doc_ids:
                    log.info(
                        "⬇️ eval — graph-ingesting %d doc(s) · run_id=%s",
                        len(doc_ids),
                        rid,
                    )
                    await _run_graph_ingest_for_documents(
                        service,
                        workspace_path,
                        doc_ids,
                        source_role="user_document",
                    )
                else:
                    log.warning(
                        "⚠️ eval — build_graph requested but no synthetic docs found "
                        "(tag=%s) · skipping",
                        EVAL_SYNTHETIC_TAG,
                    )

            log.info(
                "▶ eval — running questions · run_id=%s · corpus=%s · questions=%s",
                rid,
                DEFAULT_CORPUS_DIR,
                DEFAULT_QUESTIONS_FILE,
            )
            summary = await run_eval(service, workspace_path, run_id=rid)
            return {
                "run_id": rid,
                "summary": summary.to_payload(),
                "questions": [
                    q.to_payload(index=i, total=len(summary.questions))
                    for i, q in enumerate(summary.questions)
                ],
                "ingested_synthetic": bool(ingest_synthetic),
                "built_graph": bool(build_graph),
            }
        finally:
            if owned:
                await _close_if_owned(service, owned)


__all__ = ["KnowledgeL3EvalRunTool"]
