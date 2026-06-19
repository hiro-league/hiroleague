"""Knowledge-track eval runner.

Runs each question through ``service.answer_legs`` (flat + graphiti legs share one
query/rewrite/embedder/rerank; only ``use_graph`` differs), optionally LLM-judges each
leg, and summarizes with the PROCEED/PIVOT gate. Setup helpers ingest the synthetic
corpus and clear per-corpus eval docs. Publishes ``eval.*`` Domain Events.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from hirocli.domain.events import get_domain_event_bus
from hirocli.runtime.agent_graph.tracing import traced_run
from hirocli.services.eval.constants import (
    EVAL_COMPLETED,
    EVAL_FAILED,
    EVAL_QUESTION_COMPLETED,
    EVAL_SETUP_PROGRESS,
    EVAL_STARTED,
)
from hirocli.services.knowledge.converters import utc_now_iso
from hirocli.services.knowledge.graph.group_scope import slug_group_part

from hirocli.services.eval.corpus import (
    DEFAULT_CORPUS_DIR,
    EVAL_SYNTHETIC_TAG,
    eval_kb_tag,
    load_questions,
)
from hirocli.services.eval.events import _publish, _raise_if_cancelled
from hirocli.services.eval.models import (
    EvalSummary,
    LegResult,
    QuestionResult,
    build_eval_judge_model,
    normalize_modes,
)
from hirocli.services.eval.summary import _best_graph_delta_marks, _summarize

log = Logger.get("SVC.KNOWLEDGE.EVAL")


async def run_eval(
    service: Any,
    workspace_path: Path,
    *,
    questions: list[dict[str, Any]] | None = None,
    run_id: str | None = None,
    filters: dict[str, Any] | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    modes: list[str] | None = None,
    judge: bool = False,
) -> EvalSummary:
    """Run the question loop against ``service`` — emitting events as it goes.

    Assumes the synthetic corpus + graph are already ingested. (Setup is a
    separate concern; the Tool wraps both.)

    Each question runs via ``service.compare`` so both legs (flat / graph)
    share the same query/rewrite/embedder/rerank — only ``use_graph`` differs.
    The filter (``tags=["_l3_eval_synthetic"]`` by default) scopes retrieval
    to the synthetic corpus so unrelated workspace docs don't pollute results.

    ``run_id`` is generated if not provided; events carry it so the UI can
    correlate event stream → row updates.
    """
    bus = get_domain_event_bus()
    rid = run_id or f"l3eval-{uuid.uuid4()}"
    questions = questions if questions is not None else load_questions()
    total = len(questions)
    run_modes = normalize_modes(modes)
    started_at = time.perf_counter()

    # Default the synthetic-tag filter unless the caller passed their own.
    eval_filters: dict[str, Any] = dict(filters or {})
    eval_filters.setdefault("tags", [EVAL_SYNTHETIC_TAG])

    # Optional LLM judge: build the eval JUDGE model + a ledger sink (so judge calls show as
    # priced Graph Runs). The knowledge legs ANSWER with the production KnowledgeAgentGraph (not an
    # eval model), so only the judge model is eval-configurable here. Judge off / no model → legs
    # carry the answer but no mark, and the gate is n/a.
    model, model_id = (build_eval_judge_model(workspace_path) if judge else (None, ""))
    # Always create the sink — even judge-off — so per-leg cost can be read back from the
    # ledger (cost is NOT judge-dependent). Judge rows are only written when judging.
    from hirocli.runtime.agent_graph.ledger import LedgerSink

    sink = LedgerSink(workspace_path)
    judged = model is not None
    # Editable judge grading prompt (graph.eval.judge_prompt); blank → default in judge.
    from hirocli.domain.preferences import load_preferences

    judge_prompt = load_preferences(workspace_path).graph.eval.judge_prompt

    _publish(
        bus,
        workspace_path,
        EVAL_STARTED,
        {
            "run_id": rid,
            "total_questions": total,
            "track": "knowledge",
            "filters": eval_filters,
            # Selected legs — the UI needs these up front to render the right
            # columns before the first question row arrives.
            "modes": run_modes,
            "judged": judged,
        },
    )

    rows: list[QuestionResult] = []
    # One LangSmith root span for the whole run so each question's answer legs + judge
    # nest under it instead of scattering as independent roots. run_id = uuid5(rid) ⇒ the
    # admin "open in LangSmith" link (langsmith_url_for_run) resolves it. No-op when off.
    with traced_run(
        "knowledge_eval",
        ledger_run_id=rid,
        tags=["eval", "knowledge", f"judge:{judged}"],
        metadata={"total_questions": total, "modes": run_modes, "filters": eval_filters},
    ):
        try:
            for index, q in enumerate(questions):
                # Cooperative cancel: bail before starting the next question if a Cancel was
                # requested, even if task.cancel()'s CancelledError got swallowed downstream.
                _raise_if_cancelled(workspace_path, rid)
                # Per-question child span — answer legs (each its own knowledge_answer run)
                # and the judge call attach here, so a question reads as one subtree.
                with traced_run(
                    "eval_question",
                    tags=["eval", "knowledge", str(q.get("category") or "")],
                    metadata={
                        "id": q.get("id"),
                        "requires_graph": bool(q.get("requires_graph")),
                    },
                    inputs={"question": q.get("question", "")},
                ):
                    result = await _run_one_question(
                        service,
                        q,
                        modes=run_modes,
                        filters=eval_filters,
                        top_k=top_k,
                        min_score=min_score,
                        model=model,
                        model_id=model_id,
                        judge=judged,
                        sink=sink,
                        run_id=rid,
                        judge_system_prompt=judge_prompt,
                    )
                rows.append(result)
                # run_id on every event so the per-workspace registry can attribute
                # this row to the right run (the registry replays state on mount /
                # cross-origin; see registry.py).
                _publish(
                    bus,
                    workspace_path,
                    EVAL_QUESTION_COMPLETED,
                    {"run_id": rid, **result.to_payload(index=index, total=total)},
                )
        except Exception as exc:
            log.error(
                "❌ knowledge.eval — run aborted",
                run_id=rid,
                error=str(exc),
                exc_info=True,
            )
            _publish(
                bus,
                workspace_path,
                EVAL_FAILED,
                {"run_id": rid, "error": f"{type(exc).__name__}: {str(exc)[:200]}"},
            )
            raise

    summary = _summarize(rid, rows, started_at, run_modes, judged=judged)
    log.info(
        "✅ knowledge.eval — run complete · gate=%s · judged=%s · cost=$%.4f (Q; ingest deferred) · ms=%d",
        summary.gate,
        judged,
        summary.questions_cost_usd,
        summary.elapsed_ms,
    )
    _publish(
        bus,
        workspace_path,
        EVAL_COMPLETED,
        summary.to_payload(),
    )
    return summary


# ---------------------------------------------------------------------------
# Setup helpers (called by the Tool when the caller asks for it)
# ---------------------------------------------------------------------------


async def ingest_synthetic_corpus_via_service(
    service: Any,
    workspace_path: Path,
    *,
    corpus_dir: Path | None = None,
    tag: str = EVAL_SYNTHETIC_TAG,
    run_id: str | None = None,
) -> list[str]:
    """Ingest the synthetic corpus into the workspace's knowledge index and
    return the freshly-ingested document_ids.

    Tags every ingested doc with the eval tag so retrieval can filter to the
    synthetic-only candidate set. Idempotent: re-running on the same workspace
    skips already-ingested docs via the existing content_hash dedup.
    """
    target = corpus_dir or DEFAULT_CORPUS_DIR
    paths = sorted(target.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"No .md files in synthetic corpus dir: {target}")

    bus = get_domain_event_bus()
    _publish(
        bus,
        workspace_path,
        EVAL_SETUP_PROGRESS,
        {"run_id": run_id, "phase": "ingest_synthetic", "file_count": len(paths)},
    )

    await service.ingest_and_wait(
        [str(p) for p in paths],
        owner_kind="system",
        owner_id="0",
        tags=[tag],
    )

    # Resolve back to document_ids by source_uri match.
    docs_result = await service.list_documents(limit=500, offset=0)
    ids: list[str] = []
    target_str = str(target.resolve())
    for doc in docs_result.documents:
        if str(doc.source_uri).startswith(target_str):
            ids.append(doc.id)
    return ids


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _run_one_question(
    service: Any,
    q: dict[str, Any],
    *,
    modes: list[str],
    filters: dict[str, Any],
    top_k: int | None,
    min_score: float | None,
    model: Any | None = None,
    model_id: str = "",
    judge: bool = False,
    sink: Any | None = None,
    run_id: str = "",
    judge_system_prompt: str = "",
) -> QuestionResult:
    """One knowledge question → N-leg fan-out (answer per leg) → optional LLM judge → one row.

    ``answer_legs`` already ledgers each leg's answer as its own Graph Run. When ``judge`` is on,
    the leg's answer is graded by the LLM judge (vs the ideal ``expected_answer``) inside a
    per-question ``knowledge_eval_judge`` run, so the verdict's grading call shows in Graph Runs
    too. With ``judge`` off, legs carry the answer but no mark (answers-only)."""
    from hirocli.services.eval.judge import judge_answer

    results = await service.answer_legs(
        q["question"],
        modes=modes,
        top_k=top_k,
        min_score=min_score,
        filters=filters,
        rewrite=True,
    )
    gold = q.get("expected_answer", "")
    is_control = str(q.get("expected_kind") or "") == "abstain"
    # Per-leg cost — each leg's answer already ran as its own (now-written) Graph Run; read the
    # folded cost back by run_id (LLM + reranker; embeddings unpriced). Judge cost added below.
    leg_run_ids = {getattr(r, "run_id", None) for r in results.values() if getattr(r, "run_id", None)}
    leg_costs = sink.read_run_costs(leg_run_ids) if sink is not None else {}
    legs: dict[str, LegResult] = {}
    marks: dict[str, str] = {}

    # Optional judge: one run per question holding a judge node per leg (priced in Graph Runs).
    judging = judge and model is not None and sink is not None
    run_token = None
    if judging:
        from hirocli.runtime.agent_graph.ledger import RunAccumulator, current_run

        acc = RunAccumulator(
            sink=sink,
            run_id=f"knowledge_eval_judge-{run_id}-{slug_group_part(str(q.get('id') or ''))}",
            inbound_id=str(q.get("id") or ""),
        )
        run_token = current_run.set(acc)
    try:
        for mode in modes:  # preserve requested column order
            res = results.get(mode)
            if res is None:
                continue
            answer = res.answer or ""
            mark, reason, evidence = "", "", ""
            grounded, recall_sufficient = True, True
            if judging:
                verdict = await judge_answer(
                    model,
                    model_id,
                    question=q["question"],
                    answer=answer,
                    expected_answer=gold,
                    is_negative_control=is_control,
                    sink=sink,
                    system_prompt=judge_system_prompt,
                )
                mark, reason = verdict.mark, verdict.reason
                grounded, recall_sufficient = verdict.grounded, verdict.recall_sufficient
                evidence = verdict.evidence
            marks[mode] = mark
            legs[mode] = LegResult(
                mode=mode,
                mark=mark,
                elapsed_ms=int(res.elapsed_ms or 0),
                answer=answer,
                run_id=getattr(res, "run_id", None),
                reason=reason,
                cost_usd=float(leg_costs.get(str(getattr(res, "run_id", "") or ""), 0.0)),
                grounded=grounded,
                recall_sufficient=recall_sufficient,
                evidence=evidence,
            )
        if judging:
            sink.write_run_row(
                acc,
                status="completed",
                decision_kind="completed",
                decision_detail="knowledge_eval_judge",
                input_preview=f"q: {q['question'][:160]}",
                output_preview=" ".join(f"{m}:{mk or '—'}" for m, mk in marks.items()),
            )
    finally:
        if run_token is not None:
            from hirocli.runtime.agent_graph.ledger import current_run as _cr

            sink.evict_run(acc.run_id)
            _cr.reset(run_token)
    # Whole-question cost = sum of leg answer runs + the judge run (when judged).
    judge_cost = float(getattr(acc, "cost_usd", 0.0) or 0.0) if judging else 0.0
    question_cost = sum(leg.cost_usd for leg in legs.values()) + judge_cost
    return QuestionResult(
        id=q["id"],
        category=q.get("category", ""),
        subcategory=q.get("subcategory", ""),
        difficulty=q.get("difficulty", ""),
        question=q["question"],
        requires_graph=bool(q.get("requires_graph")),
        legs=legs,
        delta=_best_graph_delta_marks(marks),
        track="knowledge",
        gold=gold,
        cost_usd=question_cost,
        is_negative_control=is_control,
        answered_at=utc_now_iso(),
    )


async def collect_synthetic_doc_ids(service: Any) -> list[str]:
    """Return doc_ids of every workspace document carrying the eval tag.

    Used by the ``ingest_synthetic=False, build_graph=True`` path — graph-build
    over docs already in the workspace without re-ingesting. Also handy from the
    admin route so the UI can show "no synthetic docs found, ingest first" hints.
    """
    docs_result = await service.list_documents(tag=EVAL_SYNTHETIC_TAG, limit=500)
    return [d.id for d in docs_result.documents]


async def collect_eval_doc_ids(service: Any, corpus_id: str) -> list[str]:
    """Return doc_ids of one KNOWLEDGE-track eval corpus (tag ``_eval_kb_{corpus_id}``).

    The memory track no longer writes knowledge documents (its data lives in the
    ``eval_mem_{set}`` graph drawer, cleared by group — not by document), so the knowledge
    eval footprint is exactly this corpus's tagged docs."""
    docs_result = await service.list_documents(tag=eval_kb_tag(corpus_id), limit=500)
    return [doc.id for doc in docs_result.documents]


async def clear_eval_data(service: Any, corpus_id: str) -> int:
    """Delete one KNOWLEDGE-track eval corpus — catalog rows, Qdrant chunks, and graph
    episodes — and return the document count removed.

    Scopes to the LIVE per-corpus tag (``_eval_kb_{corpus_id}``): ``service.delete_document``
    purges all three stores per document (catalog + Qdrant + graph episodes). Idempotent: a
    corpus with no eval docs removes 0. (The MEMORY track clears separately by graph group —
    ``clear_all`` / ``clear_group("eval_mem_{set}")``.)
    """
    doc_ids = await collect_eval_doc_ids(service, corpus_id)
    if not doc_ids:
        log.info("🧹 knowledge.eval — no eval documents to clear · corpus=%s", corpus_id)
        return 0
    removed = 0
    for doc_id in doc_ids:
        try:
            result = await service.delete_document(doc_id)
        except Exception:
            # External stores (catalog/Qdrant/Kuzu) — log + continue so one stuck doc
            # doesn't strand the rest of the eval wipe.
            log.warning(
                "⚠️ knowledge.eval — failed to delete eval doc · doc_id=%s", doc_id, exc_info=True
            )
            continue
        if result.get("deleted"):
            removed += 1
    log.info(
        "🧹 knowledge.eval — cleared eval data · corpus=%s · documents=%d/%d",
        corpus_id,
        removed,
        len(doc_ids),
    )
    return removed
