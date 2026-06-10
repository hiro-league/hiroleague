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
    DEFAULT_CORPUS_DIR,
    DEFAULT_MEMORY_EVAL_SET,
    DEFAULT_QUESTIONS_FILE,
    EVAL_SYNTHETIC_TAG,
    collect_synthetic_doc_ids,
    ingest_synthetic_corpus_via_service,
    load_adam_questions,
    load_questions,
    run_eval,
    run_memory_eval,
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
        "track": ToolParam(
            str,
            "Eval track: 'knowledge' (default — document/chunk corpus → ingest+retrieval, "
            "flat vs graphiti) or 'memory' (turn corpus → conversation remember/recall, "
            "single recall leg, no gate; data lands in the eval_mem_{set} drawer).",
            required=False,
        ),
        "ingest_synthetic": ToolParam(
            bool,
            "knowledge: ingest eval/l3_synthetic/*.md (auto-tagged _l3_eval_synthetic). "
            "memory: remember the turn corpus into eval_mem_{set} first. "
            "Skip if already populated. Default false.",
            required=False,
        ),
        "build_graph": ToolParam(
            bool,
            "knowledge only: graph-ingest the synthetic docs after standard ingest. "
            "Skip if graph already built. Default false.",
            required=False,
        ),
        "question_ids": ToolParam(
            list[str],
            "Run just these question ids (empty = all). Applies to the memory track "
            "and the knowledge Adam-less bank.",
            required=False,
        ),
        "modes": ToolParam(
            list[str],
            "knowledge only — legs to compare: any subset of ['flat','graphiti'] (one is "
            "fine). Empty = all. Ignored on the memory track (single recall leg).",
            required=False,
        ),
        "judge": ToolParam(
            bool,
            "Run the optional LLM judge (grades the model's answer vs the ideal answer, "
            "reusing the answering model). Off = answers only, no marks. Default false.",
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
        track: str = "knowledge",
        ingest_synthetic: bool = False,
        build_graph: bool = False,
        question_ids: list[str] | None = None,
        modes: list[str] | None = None,
        judge: bool = False,
        run_id: str = "",
        workspace: str | None = None,
    ) -> dict[str, Any]:
        return asyncio.run(
            self.execute_async(
                track=track,
                ingest_synthetic=ingest_synthetic,
                build_graph=build_graph,
                question_ids=question_ids,
                modes=modes,
                judge=judge,
                run_id=run_id,
                workspace=workspace,
            )
        )

    async def execute_async(
        self,
        track: str = "knowledge",
        ingest_synthetic: bool = False,
        build_graph: bool = False,
        question_ids: list[str] | None = None,
        modes: list[str] | None = None,
        judge: bool = False,
        run_id: str = "",
        workspace: str | None = None,
    ) -> dict[str, Any]:
        rid = (run_id or "").strip() or f"l3eval-{uuid.uuid4()}"
        runtime = getattr(self, "_runtime", None)
        service, workspace_path, owned = _resolve_service(runtime, workspace)
        try:
            # Memory track: turn corpus → conversation remember/recall in the eval_mem_{set}
            # drawer (an eval-scoped memory facade — independent of memory.enabled). ``ingest_synthetic``
            # doubles as "remember the corpus" so question subsets re-run without re-remembering.
            if track == "memory":
                from ..domain.preferences import load_preferences
                from ..services.memory import create_eval_memory_service

                prefs = load_preferences(workspace_path)
                memory = create_eval_memory_service(
                    workspace_path, prefs, set_id=DEFAULT_MEMORY_EVAL_SET
                )
                try:
                    questions = load_adam_questions()
                    if question_ids:
                        wanted = set(question_ids)
                        questions = [q for q in questions if q["id"] in wanted]
                    summary = await run_memory_eval(
                        memory,
                        workspace_path,
                        set_id=DEFAULT_MEMORY_EVAL_SET,
                        questions=questions,
                        run_id=rid,
                        remember=ingest_synthetic,
                        # The tool is a one-shot rebuild (no batching): clearing the drawer is now
                        # decoupled from remember in the runner, so pair them here to keep this
                        # path's "ingest = rebuild from scratch" behavior unchanged.
                        clear_before=ingest_synthetic,
                        judge=judge,
                    )
                finally:
                    await memory.close()
                return {"run_id": rid, "track": "memory", "summary": summary}

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
            summary = await run_eval(
                service, workspace_path, run_id=rid, modes=modes, judge=judge
            )
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
