"""Admin routes for workspace-local eval (memory + knowledge retrieval evaluation).

Split out of ``routes/knowledge.py`` (initial-dev mode, no back-compat): the eval batch
endpoints now live under ``/eval/*`` instead of ``/knowledge/eval/*``. They still reuse the
shared knowledge-service route helpers (``_resolve_service`` / ``_success`` / ...) and the
eval progress events still ride the shared ``/knowledge/events`` SSE stream (connection
budget) — only the HTTP surface moved.
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hiro_commons.log import Logger

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import envelope_failure
from hirocli.admin_svelte.routes.knowledge import (
    _close_if_owned,
    _publish_graph_event,
    _resolve_service,
    _success,
)
from hirocli.domain.events import DomainEvent, get_domain_event_bus
from hirocli.domain.workspace import resolve_workspace
from hirocli.services.eval.constants import (
    EVAL_CANCELLED,
    EVAL_FAILED,
)
from hirocli.services.knowledge.graph.group_scope import KNOWLEDGE_GROUP_ID

log = Logger.get("ADMIN.EVAL")

eval_router = APIRouter()


class EvalRunBody(BaseModel):
    """L3 (Phase 5e) — request body for ``POST /eval/run``.

    The eval runs in the background; the response returns the ``run_id``
    immediately, and progress events stream out on ``/knowledge/events``."""

    # Eval track (docs/eval-corpus-tracks-design.md): "knowledge" (document/chunk corpus →
    # ingest+retrieval) or "memory" (turn corpus → conversation remember/recall, eval_mem_{set}).
    track: str = "knowledge"
    # Chosen corpus (from the corpus picker): the id doubles as the eval drawer suffix
    # (eval_mem_{id} / eval_kb_{id}); corpus_path is the .episodes.jsonl file (memory) or the
    # folder of .md docs (knowledge); questions_path is the paired <id>.questions.yaml.
    corpus_id: str = ""
    corpus_path: str = ""
    questions_path: str = ""
    # Remember the turn corpus (memory) / ingest the doc corpus (knowledge) before running.
    ingest_synthetic: bool = False
    build_graph: bool = False  # knowledge only
    # Memory track — explicitly wipe the eval graph BEFORE remembering. Decoupled from
    # ``ingest_synthetic`` so a corpus can be built across appended batches without each batch
    # wiping the last; set it only for a from-scratch rebuild (first batch). Default off ⇒ the
    # graph is never cleared implicitly.
    clear_before: bool = False
    # Memory track — episode batch window for the remember phase: start index + max count into
    # the (chronologically sorted) corpus. 0 / None = from the start / to the end. Lets a large
    # corpus be remembered in monitored chunks. Ignored on the knowledge track.
    episode_offset: int = 0
    episode_limit: int | None = None
    # Optional LLM judge step: grade the model's answer against the ideal answer. When off, the
    # eval generates answers but assigns no marks (and no PROCEED/PIVOT gate).
    judge: bool = False
    # Memory track — max questions running their recall→answer→judge legs at once (1 = serial).
    # Clamped server-side to [1, MAX_QUESTION_CONCURRENCY] rather than 422-ing an out-of-range
    # value. Ignored on the knowledge track (its leg loop is still serial — named follow-up).
    question_concurrency: int = 1
    # Selected question ids — REQUIRED and non-empty (the UI forces an explicit selection;
    # there is no implicit "run all").
    question_ids: list[str] | None = None
    # Knowledge track only — legs to compare, subset of ["flat", "graphiti"] (one is fine).
    # None/empty = both. Normalized server-side. Ignored on the memory track (single recall leg).
    modes: list[str] | None = None
    run_id: str | None = None


@eval_router.post("/eval/run")
async def eval_run(
    body: EvalRunBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """L3 (Phase 5e) — kick the synthetic eval batch in the background.

    Returns ``{run_id}`` immediately. The eval emits ``eval.*`` Domain
    Events as it goes; the admin UI subscribes via ``/knowledge/events`` to
    update the live progress table. Tied to the workspace_id; the SSE filter
    drops events for other workspaces.
    """
    # Local imports keep the module's top-level deps thin — eval is a niche path.
    from hirocli.services.eval.registry import get_eval_registry
    from hirocli.services.eval.runner import (
        MAX_QUESTION_CONCURRENCY,
        eval_kb_tag,
        ingest_synthetic_corpus_via_service,
        load_questions,
        normalize_modes,
        run_eval,
        run_memory_eval,
    )
    from hirocli.tools.knowledge_graph import (
        _run_graph_ingest_for_documents,
        remove_document_from_graph,
    )

    try:
        service, owned = await _resolve_service(request, workspace_id)
        run_id = (body.run_id or "").strip() or f"l3eval-{uuid.uuid4()}"
        workspace_path = service.workspace_path
        # Memory track runs a single recall leg (no flat/graphiti); knowledge keeps the leg set.
        run_modes = ["recall"] if body.track == "memory" else normalize_modes(body.modes)

        # Resolve + validate the chosen corpus and question selection up front, so a bad
        # request fails the HTTP call directly (not as a silent background crash). Questions are
        # an explicit selection (no implicit "run all"), but may be empty for a setup-only batch
        # (remember/ingest/build/clear) — see the setup_only check below.
        corpus_id = (body.corpus_id or "").strip()
        corpus_path = (body.corpus_path or "").strip()
        questions_path = (body.questions_path or "").strip()
        selected_ids = [q for q in (body.question_ids or []) if q]
        if not corpus_id or not corpus_path:
            return envelope_failure("Pick a corpus before running the eval.")
        # Setup-only runs (remember/ingest/build/clear a batch with NO questions) are allowed —
        # that's how a large corpus gets built in monitored chunks before any recall. A run with
        # neither questions nor a setup action would do nothing, so reject only that case.
        setup_only = body.ingest_synthetic or body.build_graph or body.clear_before
        if not selected_ids and not setup_only:
            return envelope_failure(
                "Select at least one question, or enable Remember / Clear for a setup-only batch."
            )
        # Questions need their bank; a setup-only batch doesn't. Load + filter to the explicit
        # selection (preserving bank order). Empty selection ⇒ no questions (setup-only run).
        questions: list[dict[str, Any]] = []
        if selected_ids:
            if not questions_path or not Path(questions_path).exists():
                return envelope_failure(
                    f"No question bank found for corpus '{corpus_id}' "
                    f"(expected {corpus_id}.questions.yaml beside the corpus)."
                )
            wanted = set(selected_ids)
            questions = [q for q in load_questions(Path(questions_path)) if q["id"] in wanted]
            if not questions:
                return envelope_failure("None of the selected question ids exist in the bank.")
        # Subscribe the per-workspace run registry BEFORE the task starts so it
        # captures the full event trail for mid-run replay / cross-origin reads.
        registry = get_eval_registry()
        registry.ensure_subscribed()

        async def _runner() -> None:
            # All exceptions caught inside the task: a background-task crash that
            # bubbles up to the asyncio loop has nowhere to go (no awaiter) and
            # the UI would see "FAILED" event but no error context. We log the
            # full traceback ourselves and emit the FAILED event (run_eval
            # already does on its own exceptions; setup-phase exceptions are
            # handled explicitly here).
            try:
                # Memory track: remember the chosen turn corpus into its eval_mem_{corpus_id}
                # drawer via an eval-scoped memory facade, then recall per question. Single recall
                # leg, no gate (docs §8). ``ingest_synthetic`` doubles as "remember the corpus" so
                # question subsets re-run without re-remembering. Independent of memory.enabled.
                if body.track == "memory":
                    from hirocli.domain.preferences import load_preferences
                    from hirocli.services.memory import create_eval_memory_service

                    prefs = load_preferences(workspace_path)
                    memory = create_eval_memory_service(
                        workspace_path, prefs, set_id=corpus_id
                    )
                    # Clamp (don't reject) the question-phase cap — a stale/edited client
                    # value should degrade to the nearest legal cap, not fail the run.
                    concurrency = max(
                        1, min(int(body.question_concurrency or 1), MAX_QUESTION_CONCURRENCY)
                    )
                    try:
                        log.info(
                            "⬇️ knowledge.eval — memory track · corpus=%s · remember=%s · "
                            "clear=%s · range=[%s:%s] · concurrency=%d · run_id=%s",
                            corpus_id,
                            body.ingest_synthetic,
                            body.clear_before,
                            body.episode_offset,
                            body.episode_limit,
                            concurrency,
                            run_id,
                        )
                        await run_memory_eval(
                            memory,
                            workspace_path,
                            set_id=corpus_id,
                            corpus_path=Path(corpus_path),
                            # questions_path lets the runner load the LoCoMo sidecar and emit
                            # per-question evidence recall LIVE (EV column / fold) instead of only
                            # on the post-run results refresh. Empty on a setup-only batch.
                            questions_path=Path(questions_path) if questions_path else None,
                            questions=questions,
                            run_id=run_id,
                            remember=body.ingest_synthetic,
                            clear_before=body.clear_before,
                            episode_offset=body.episode_offset,
                            episode_limit=body.episode_limit,
                            judge=body.judge,
                            question_concurrency=concurrency,
                        )
                    finally:
                        await memory.close()
                    return

                # Knowledge track: ingest the chosen .md corpus folder (tagged per corpus so
                # retrieval scopes to it), optionally build the graph, then run flat/graphiti.
                eval_tag = eval_kb_tag(corpus_id)
                ingested_ids: list[str] = []
                if body.ingest_synthetic:
                    # Re-ingest = clean slate. Drop this corpus's prior eval docs (catalog +
                    # Qdrant chunks + their graph episodes) BEFORE re-ingesting, so a re-run
                    # starts fresh. Re-ingesting over existing chunks/graph let stale state
                    # contaminate retrieval + Graphiti dedup (memory-track parity). Gated on the
                    # checkbox: a subset re-run (both off) reuses the existing index.
                    prior = await service.list_documents(tag=eval_tag, limit=500)
                    for doc in prior.documents:
                        await service.delete_document(doc.id)
                    if prior.documents:
                        log.info(
                            "🧹 knowledge.eval — cleared %d prior eval doc(s) · corpus=%s",
                            len(prior.documents),
                            corpus_id,
                        )
                    log.info(
                        "⬇️ knowledge.eval — ingesting corpus '%s' · run_id=%s",
                        corpus_id,
                        run_id,
                    )
                    ingested_ids = await ingest_synthetic_corpus_via_service(
                        service,
                        workspace_path,
                        corpus_dir=Path(corpus_path),
                        tag=eval_tag,
                        run_id=run_id,
                    )
                if body.build_graph:
                    # When ingest was skipped, find this corpus's docs by its eval tag.
                    if ingested_ids:
                        doc_ids = ingested_ids
                    else:
                        docs = await service.list_documents(tag=eval_tag, limit=500)
                        doc_ids = [d.id for d in docs.documents]
                    # Rebuild = clean slate. On a build-ONLY run (ingest off, reusing existing
                    # chunks) wipe these docs' prior graph episodes first so the graph rebuilds
                    # clean — re-ingesting episodes over the old graph let Graphiti dedup against
                    # stale state. When ingest just ran, the docs are fresh with no graph yet, so
                    # the delete_document above already cleared it → skip this pass.
                    if doc_ids and not body.ingest_synthetic:
                        for did in doc_ids:
                            await remove_document_from_graph(workspace_path, did)
                        log.info(
                            "🧹 knowledge.eval — cleared prior graph for %d doc(s) · corpus=%s",
                            len(doc_ids),
                            corpus_id,
                        )
                    if doc_ids:
                        log.info(
                            "⬇️ knowledge.eval — graph-ingesting %d doc(s) · run_id=%s",
                            len(doc_ids),
                            run_id,
                        )
                        await _run_graph_ingest_for_documents(
                            service,
                            workspace_path,
                            doc_ids,
                            source_role="user_document",
                            # Emit live node/edge events so the Graph tab updates while the
                            # eval's graph build runs (matches the ingest_batch path). Without
                            # this sink the eval build was silent → no live viz updates.
                            event_sink=functools.partial(
                                _publish_graph_event, workspace_path
                            ),
                        )
                        # Burst over — let the Graph tab run one reconciling full export to
                        # heal any deltas dropped under the SSE queue cap (mirrors ingest_batch).
                        _publish_graph_event(
                            workspace_path,
                            KNOWLEDGE_GRAPH_INGEST_COMPLETED,
                            # Knowledge-eval graph docs ingest into the default kb_main group;
                            # tag the completion so the Graph tab gates the clear/reconcile by
                            # the partition it's viewing (mirrors ingest_progress' group_id).
                            {
                                "document_count": len(doc_ids),
                                "totals": {},
                                "group_id": KNOWLEDGE_GROUP_ID,
                            },
                        )
                    else:
                        log.warning(
                            "⚠️ knowledge.eval — build_graph requested but no "
                            "synthetic docs in workspace · run_id=%s",
                            run_id,
                        )
                # run_eval emits started / question_completed / completed / failed
                # events on its own — scoped to this corpus's docs + selected questions.
                await run_eval(
                    service,
                    workspace_path,
                    questions=questions,
                    run_id=run_id,
                    filters={"tags": [eval_tag]},
                    modes=run_modes,
                    judge=body.judge,
                )
            except asyncio.CancelledError:
                # User pressed Cancel (the cancel route called task.cancel(), which
                # raises here at the next await). Emit the neutral terminal CANCELLED
                # event so the panel stops spinning and reads it as "stopped", not
                # "failed". Re-raise so the task is properly marked cancelled.
                log.info("🛑 knowledge.eval — run cancelled · run_id=%s", run_id)
                get_domain_event_bus().publish(
                    DomainEvent(
                        type=EVAL_CANCELLED,
                        workspace_path=workspace_path,
                        payload={"run_id": run_id},
                    )
                )
                raise
            except Exception as exc:
                log.error(
                    "❌ knowledge.eval — background run failed · run_id=%s",
                    run_id,
                    exc_info=True,
                )
                # Emit the terminal FAILED event. run_eval emits this on its OWN
                # failures, but a SETUP-phase crash (corpus ingest / build-graph) happens
                # before run_eval runs — without this the admin Eval panel never receives
                # a terminal event and spins forever. Same payload shape as run_eval.
                get_domain_event_bus().publish(
                    DomainEvent(
                        type=EVAL_FAILED,
                        workspace_path=workspace_path,
                        payload={
                            "run_id": run_id,
                            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                        },
                    )
                )
            finally:
                if owned:
                    await _close_if_owned(service, owned)

        # ``create_task`` is fire-and-forget here. The route returns immediately
        # so the UI gets ``run_id`` without blocking on the eval (which can take
        # minutes for a real corpus). Register the task with the run registry
        # synchronously (before it gets a chance to run) so a Cancel that arrives
        # before the first event still finds a handle, and so the registry holds
        # the live state for replay.
        task = asyncio.create_task(_runner())
        registry.begin_run(
            workspace_path,
            run_id,
            corpus_source=corpus_id,
            modes=run_modes,
            task=task,
            track=body.track,
        )
        return _success({"run_id": run_id})
    except Exception as exc:
        log.error(
            "knowledge eval run failed to start · workspace=%s · %s",
            workspace_id,
            str(exc),
            exc_info=True,
        )
        return envelope_failure(str(exc))


@eval_router.get("/eval/state")
async def eval_state(
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    """L3 — replay the latest eval run's live state for this workspace.

    The admin panel calls this on mount so leaving + returning (or opening the
    Vite dev UI vs the packaged UI — different origins, separate sessionStorage)
    shows the SAME run: the setup activity trail, the per-question rows with full
    answers, and the summary. ``data`` is ``null`` when no run exists (idle, or
    the server restarted since the last run)."""
    from hirocli.services.eval.registry import get_eval_registry

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        state = get_eval_registry().get_run(workspace_path)
        return _success(state.to_payload() if state is not None else None)
    except Exception as exc:
        log.error("knowledge eval state failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


class EvalCancelBody(BaseModel):
    """L3 — cancel a running eval. ``run_id`` is optional (defensive): when
    present we only cancel if it matches the live run, so a stale Cancel click
    from a previous run can't kill a new one."""

    run_id: str | None = None


@eval_router.post("/eval/cancel")
async def eval_cancel(
    body: EvalCancelBody,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    """L3 — request cancellation of the in-flight eval run for this workspace.

    Cancels the background task; the runner catches ``CancelledError`` and emits
    the terminal ``eval.cancelled`` event. Returns whether a live run
    was actually signalled."""
    from hirocli.services.eval.registry import get_eval_registry

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        cancelled = get_eval_registry().request_cancel(workspace_path, body.run_id)
        return _success({"cancelled": cancelled, "run_id": body.run_id})
    except Exception as exc:
        log.error("knowledge eval cancel failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@eval_router.post("/eval/clear")
async def eval_clear(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
    track: str = "knowledge",
    corpus_id: str = "",
) -> dict[str, Any]:
    """Delete a track's eval data from the workspace. Backs the Eval panel's "Clear eval data".

    - **knowledge** (default): document-scoped wipe of the chosen corpus's eval-tagged docs
      (``_eval_kb_{corpus_id}`` → catalog + Qdrant + graph episodes) via ``clear_eval_data``.
    - **memory**: group-scoped wipe of the chosen ``eval_mem_{corpus_id}`` drawer via the
      eval-scoped memory facade's ``clear_all`` (docs/eval-corpus-tracks-design.md §8.5).
    """
    if track == "memory":
        from hirocli.domain.preferences import load_preferences
        from hirocli.services.eval.runner import MEMORY_EVAL_USER_ID
        from hirocli.services.memory import create_eval_memory_service

        set_id = (corpus_id or "").strip()
        if not set_id:
            return envelope_failure("corpus_id is required to clear a memory eval drawer.")
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        try:
            prefs = load_preferences(workspace_path)
            memory = create_eval_memory_service(workspace_path, prefs, set_id=set_id)
            try:
                removed = await memory.clear_all(
                    user_id=MEMORY_EVAL_USER_ID, character_id=set_id
                )
            finally:
                await memory.close()
            # Wiping the drawer invalidates the ingested-range readout — drop it in the same
            # call so the panel can't show a range for data that's gone.
            from hirocli.services.eval.store import get_eval_result_store

            get_eval_result_store(workspace_path).clear_ranges(set_id)
            return _success({"removed_facts": removed})
        except Exception as exc:
            log.error("knowledge eval clear (memory) failed · %s", str(exc), exc_info=True)
            return envelope_failure(str(exc))

    from hirocli.services.eval.runner import clear_eval_data

    kb_corpus = (corpus_id or "").strip()
    if not kb_corpus:
        return envelope_failure("corpus_id is required to clear a knowledge eval corpus.")
    service, owned = await _resolve_service(request, workspace_id)
    try:
        removed = await clear_eval_data(service, kb_corpus)
        return _success({"removed_documents": removed})
    except Exception as exc:
        log.error("knowledge eval clear failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))
    finally:
        await _close_if_owned(service, owned)


@eval_router.get("/eval/results")
async def eval_results(
    workspace_id: SelectedWorkspaceIdDep,
    track: str = "memory",
    corpus_id: str = "",
    questions_path: str = "",
) -> dict[str, Any]:
    """Persisted per-corpus eval results (the merged snapshot) — backs "show latest".

    Memory track only. Joins the CURRENT question bank (the spine — so edited
    question text/category/ideal show fresh) with the saved per-question rows, in
    bank order, and recomputes the merged summary over the whole accumulated set.
    Questions in the bank with no saved row are simply absent here (the checklist
    surfaces them as "not run"). Returns ``{rows, summary}``; both empty when
    nothing has been saved for the corpus."""
    if track != "memory":
        # Knowledge results aren't persisted yet (the store is memory-only for now).
        return _success({"rows": [], "summary": None})
    cid = (corpus_id or "").strip()
    if not cid:
        return envelope_failure("corpus_id is required to read eval results.")
    from hirocli.services.eval.runner import load_questions, summarize_memory_rows
    from hirocli.services.eval.store import (
        coalesce_ingested_ranges,
        get_eval_result_store,
    )

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        store = get_eval_result_store(workspace_path)
        stored = store.read_corpus(cid)
        # Ingested-range readout (build progress). Read BEFORE the no-rows early-return: a
        # remember-only build has ingested ranges but zero saved question rows, so returning
        # early on empty `stored` would hide its progress.
        raw_ranges = store.read_ranges(cid)
        spans = coalesce_ingested_ranges(raw_ranges)
        # Cumulative per-corpus ingest cost = sum of every recorded batch's cost (re-ingesting an
        # offset overwrites that batch's row, so this never double-counts). This is the ONLY place
        # ingest cost survives a reload — the per-question rows never carry it — so the panel's Cost
        # strip reads it even for a remember-only corpus with zero saved questions.
        ingest_cost_usd = sum(float(r.get("cost_usd") or 0.0) for r in raw_ranges)
        ingested = {
            "ranges": spans,  # sorted, inclusive [start, end] episode-index spans
            "count": sum(end - start + 1 for start, end in spans),  # distinct episodes ingested
            "batches": len(raw_ranges),  # how many remember batches recorded
            "cost_usd": ingest_cost_usd,  # cumulative ingest (graph-build) spend for this corpus
        }
        if not stored:
            return _success({"rows": [], "summary": None, "ingested": ingested})
        # Bank is the spine: order rows by the bank and refresh their display fields
        # from it. Falls back to stored order/fields if the bank is missing (corpus
        # moved/renamed) so saved results are never lost behind a path mismatch.
        qpath = Path(questions_path.strip()) if questions_path.strip() else None
        bank = load_questions(qpath) if qpath and qpath.exists() else []
        if bank:
            bank_by_id = {q["id"]: q for q in bank}
            ordered_ids = [q["id"] for q in bank if q["id"] in stored]
        else:
            bank_by_id = {}
            ordered_ids = list(stored.keys())
        total = len(ordered_ids)
        merged: list[dict[str, Any]] = []
        for index, qid in enumerate(ordered_ids):
            row = dict(stored[qid])
            q = bank_by_id.get(qid)
            if q is not None:
                # Refresh spine fields from the bank (edits show immediately); keep the
                # saved legs/answer/recall/mark/cost — those are the actual results.
                row["question"] = q.get("question", row.get("question", ""))
                row["category"] = q.get("category", row.get("category", ""))
                row["subcategory"] = q.get("subcategory", row.get("subcategory", ""))
                row["difficulty"] = q.get("difficulty", row.get("difficulty", ""))
                row["requires_graph"] = bool(
                    q.get("requires_graph", row.get("requires_graph"))
                )
                row["gold"] = q.get("expected_answer", row.get("gold", ""))
            # Stable display position within the merged snapshot (bank order).
            row["index"] = index
            row["total"] = total
            merged.append(row)
        # Evidence recall (LoCoMo corpora only): per question, how many gold evidence episodes the
        # recalled context covered (X/Y in the table + per-episode matched/missed in the fold).
        # Read-path enrichment computed from the saved `recalled` + the corpus sidecar — works on
        # already-saved results with no re-run. Best-effort: never let it break the results read.
        if qpath is not None:
            try:
                from hirocli.services.eval.locomo import compute_evidence_recall_map

                ev_map = compute_evidence_recall_map(
                    corpus_id=cid, questions_path=qpath, rows=merged
                )
                for row in merged:
                    ev = ev_map.get(str(row.get("id") or ""))
                    if ev is not None:
                        row["evidence_recall"] = ev
            except Exception as exc:
                log.warning(
                    "knowledge eval evidence-recall enrichment failed · %s", str(exc), exc_info=True
                )
            # Grading rubric (BEAM corpora): read-path enrichment from the corpus sidecar, so saved
            # results show the rubric in the detail dialog's judge pane without a re-run. Not
            # persisted (recomputed here, like evidence_recall). Best-effort.
            try:
                from hirocli.services.eval.locomo import load_rubric_map

                rubric_map = load_rubric_map(cid, qpath)
                for row in merged:
                    rubric = rubric_map.get(str(row.get("id") or ""))
                    if rubric:
                        row["rubric"] = rubric
            except Exception as exc:
                log.warning(
                    "knowledge eval rubric enrichment failed · %s", str(exc), exc_info=True
                )
        summary = summarize_memory_rows(merged, run_id=f"saved-{cid}")
        # The merged snapshot spans many runs, so summarize_memory_rows can't know a single ingest
        # cost (it leaves ingest_cost_usd=0). Override with the persisted CUMULATIVE ingest spend so
        # a reloaded run shows the corpus's full build cost, not just the question cost.
        summary["ingest_cost_usd"] = ingest_cost_usd
        summary["total_cost_usd"] = ingest_cost_usd + summary.get("questions_cost_usd", 0.0)
        return _success({"rows": merged, "summary": summary, "ingested": ingested})
    except Exception as exc:
        log.error("knowledge eval results read failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


def _enrich_rows_with_evidence(corpus_id: str, questions_path: str, rows: list[dict[str, Any]]) -> None:
    """Attach per-row evidence-recall (X/Y gold episodes covered) IN PLACE — the same read-path
    enrichment the per-corpus results endpoint applies, so benchmark summaries carry the
    Evidence-recall column too. Evidence is computed on read from the corpus sidecar
    (``.locomo.yaml`` / ``.beam.yaml``); it is NOT persisted in the stored rows. Best-effort: no
    sidecar / a scoring hiccup just leaves rows un-enriched (the column then shows dashes)."""
    qpath = Path(questions_path) if questions_path else None
    if qpath is None or not qpath.exists() or not rows:
        return
    try:
        from hirocli.services.eval.locomo import compute_evidence_recall_map

        ev_map = compute_evidence_recall_map(corpus_id=corpus_id, questions_path=qpath, rows=rows)
        for r in rows:
            ev = ev_map.get(str(r.get("id") or ""))
            if ev is not None:
                r["evidence_recall"] = ev
    except Exception:
        log.warning(
            "knowledge eval by-benchmark evidence enrichment failed · corpus=%s",
            corpus_id,
            exc_info=True,
        )


@eval_router.get("/eval/results/by-benchmark")
async def eval_results_by_benchmark(
    workspace_id: SelectedWorkspaceIdDep,
    benchmark: str = "",
    folder: str = "",
) -> dict[str, Any]:
    """Per-corpus + TOTAL memory-eval summaries for every corpus in a benchmark.

    Powers the benchmark results overview (one summary row per corpus + a TOTAL row over
    all their saved rows). Reuses ``summarize_memory_rows`` — the same aggregator the
    per-corpus results read uses — so the numbers match the single-corpus Report exactly.
    Memory track only. A corpus with no saved rows yet reports ``summary: null``."""
    from hirocli.services.eval.runner import (
        DEFAULT_EVAL_FOLDER,
        discover_corpuses,
        summarize_memory_rows,
    )
    from hirocli.services.eval.store import get_eval_result_store

    bid = benchmark.strip()
    if not bid:
        return envelope_failure("benchmark is required to read benchmark results.")
    try:
        base = Path(folder.strip()) if folder.strip() else DEFAULT_EVAL_FOLDER
        corpuses = [c for c in discover_corpuses(base, "memory") if c.get("benchmark") == bid]
        bench_label = corpuses[0]["benchmark_label"] if corpuses else bid
        entry, _ = resolve_workspace(workspace_id)
        store = get_eval_result_store(Path(entry.path))
        out_corpuses: list[dict[str, Any]] = []
        all_rows: list[dict[str, Any]] = []
        for c in corpuses:
            rows = list(store.read_corpus(c["id"]).values())
            # Evidence-recall isn't persisted — compute it on read (per corpus) so the benchmark
            # totals + per-corpus summaries carry the Evidence-recall column, matching the detail view.
            _enrich_rows_with_evidence(c["id"], c.get("questions_path") or "", rows)
            all_rows.extend(rows)
            out_corpuses.append(
                {
                    "corpus_id": c["id"],
                    "label": c.get("label") or c["id"],
                    "bank_questions": c.get("question_count", 0),  # questions in the bank
                    "item_count": c.get("item_count", 0),  # episodes in the corpus
                    "answered": len(rows),  # saved (run) question rows
                    "has_results": bool(rows),
                    "summary": summarize_memory_rows(rows, run_id=f"saved-{c['id']}") if rows else None,
                }
            )
        total = summarize_memory_rows(all_rows, run_id=f"benchmark-{bid}") if all_rows else None
        return _success(
            {
                "benchmark": {"id": bid, "label": bench_label},
                "corpuses": out_corpuses,
                "total": total,
            }
        )
    except Exception as exc:
        log.error("knowledge eval by-benchmark read failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


class EvalResultsClearBody(BaseModel):
    """Results-only clear of a corpus's persisted eval snapshot (memory track)."""

    track: str = "memory"
    corpus_id: str = ""


@eval_router.post("/eval/results/clear")
async def eval_results_clear(
    body: EvalResultsClearBody,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    """Delete a corpus's persisted eval RESULTS from disk (results-only).

    Distinct from ``/eval/clear`` (which wipes the ingested memory
    drawer): this removes only the saved result snapshot, leaving ingested memory
    intact so a re-run reuses it. Memory track only."""
    if body.track != "memory":
        return envelope_failure("Only the memory track persists eval results.")
    cid = (body.corpus_id or "").strip()
    if not cid:
        return envelope_failure("corpus_id is required to clear eval results.")
    from hirocli.services.eval.store import get_eval_result_store

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        removed = get_eval_result_store(workspace_path).clear_corpus(cid)
        log.info("🧹 knowledge.eval — cleared %d saved result row(s) · corpus=%s", removed, cid)
        return _success({"removed": removed})
    except Exception as exc:
        log.error("knowledge eval results clear failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@eval_router.get("/eval/row")
async def eval_row_by_run(
    workspace_id: SelectedWorkspaceIdDep,
    run_id: str = "",
) -> dict[str, Any]:
    """Resolve ONE saved memory-eval question row by its per-question graph ``run_id``.

    Backs the Graph-Runs → eval-detail bridge: a ``memory_recall`` node in a graph run carries the
    per-question ``run_id``, and this returns that question's full saved row (legs / answer /
    recall / gold / ...) so the rich eval detail dialog can open in place over the graph run.
    Memory track only — it's the only track that persists per-question rows. Returns ``{row}``
    (``row`` is ``null`` when no saved row ran under that id, e.g. results were cleared)."""
    rid = (run_id or "").strip()
    if not rid:
        return envelope_failure("run_id is required to look up an eval row.")
    from hirocli.services.eval.store import get_eval_result_store

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        row = get_eval_result_store(workspace_path).find_row_by_run_id(rid)
        if row is None:
            return _success({"row": None})
        # Spine defaults so the row renders standalone (the bridge shows one question, not a bank).
        row.setdefault("track", "memory")
        row.setdefault("index", 0)
        row.setdefault("total", 1)
        return _success({"row": row})
    except Exception as exc:
        log.error("knowledge eval row-by-run read failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@eval_router.get("/eval/results/locomo")
async def eval_results_locomo(
    workspace_id: SelectedWorkspaceIdDep,
    corpus_id: str = "",
    questions_path: str = "",
    prediction_key: str = "hiro_memory_prediction",
) -> dict[str, Any]:
    """Export saved memory-eval results in LoCoMo's QA-result JSON shape.

    The API envelope carries filename/counts for the admin UI, but ``data.content`` is the
    exact file body to download for LoCoMo evaluation: ``[{sample_id, qa: [...]}]``.
    Partial saved snapshots export the answered subset, matching LoCoMo's evaluator (it
    scores whichever QA rows are present).
    """
    cid = (corpus_id or "").strip()
    qpath = Path(questions_path.strip()) if questions_path.strip() else None
    if not cid:
        return envelope_failure("corpus_id is required to export LoCoMo results.")
    if qpath is None:
        return envelope_failure("questions_path is required to export LoCoMo results.")

    from hirocli.services.eval.locomo import (
        LocomoExportError,
        build_locomo_results_export,
    )
    from hirocli.services.eval.store import get_eval_result_store

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        stored = get_eval_result_store(workspace_path).read_corpus(cid)
        export = build_locomo_results_export(
            corpus_id=cid,
            questions_path=qpath,
            stored_rows=stored,
            prediction_key=(prediction_key or "hiro_memory_prediction").strip(),
        )
        return _success(export)
    except LocomoExportError as exc:
        return envelope_failure(str(exc))
    except Exception as exc:
        log.error("knowledge eval LoCoMo export failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@eval_router.get("/eval/corpuses")
async def eval_corpuses(
    workspace_id: SelectedWorkspaceIdDep,
    track: str = "memory",
    folder: str = "",
) -> dict[str, Any]:
    """List the corpuses in ``folder`` for ``track`` (the corpus-picker source).

    ``folder`` defaults to the sibling ``eval-corpus`` repo (``DEFAULT_EVAL_FOLDER``;
    override with ``$HIRO_EVAL_CORPUS_DIR``). Each corpus pairs with its
    ``<id>.questions.yaml`` bank by the stem convention (docs §12). The corpus files
    are workspace-independent, but each entry's ``has_graph`` flag (whether a graph was
    already built for it) is read from the selected workspace's graph — it drives the
    picker's "Rebuild graph" default + wipe warning."""
    from hirocli.services.eval.runner import DEFAULT_EVAL_FOLDER, discover_corpuses
    from hirocli.services.knowledge.graph import distinct_group_ids_with_prefix, graphiti_db_path
    from hirocli.services.knowledge.graph.group_scope import (
        EVAL_KNOWLEDGE_PREFIX,
        EVAL_MEMORY_PREFIX,
        eval_knowledge_group_id,
        eval_memory_group_id,
    )

    try:
        base = Path(folder.strip()) if folder.strip() else DEFAULT_EVAL_FOLDER
        corpuses = discover_corpuses(base, track)
        # reason: tag each corpus with whether its graph is already built, so the picker can
        # default "Rebuild graph" OFF (reuse) vs ON (build), and warn before a rebuild wipes it.
        # One DISTINCT-by-prefix read covers the whole list (membership test per corpus); a
        # graph-read hiccup degrades to has_graph=False so the picker still works.
        prefix = EVAL_MEMORY_PREFIX if track == "memory" else EVAL_KNOWLEDGE_PREFIX
        group_for = eval_memory_group_id if track == "memory" else eval_knowledge_group_id
        # reason: resolve the workspace once and hand the client its absolute ``logs/`` dir.
        # The eval "Copy for AI" brief uses it to point an investigating agent straight at the
        # on-disk ledger sidecars (retrieval_trace/<run_id>.jsonl, ingest_trace/, graph.log)
        # so it never has to search for them. log_dir is set before the (fallible) graph probe,
        # so a probe hiccup still yields the path; "" only when the workspace can't be resolved.
        log_dir = ""
        existing: set[str] = set()
        # reason: per-corpus distinct-episodes-ingested count (memory track) → drives the picker's
        # not/partial/fully-ingested status dot. Read from the workspace's eval store (the same
        # ranges the Results panel shows); a probe hiccup leaves it 0 (= not ingested) per corpus.
        ingested_by_id: dict[str, int] = {}
        try:
            entry, _ = resolve_workspace(workspace_id)
            ws_path = Path(entry.path)
            log_dir = str(ws_path / "logs")
            db_path = graphiti_db_path(ws_path)
            existing = await distinct_group_ids_with_prefix(db_path, prefix)
            if track == "memory":
                from hirocli.services.eval.store import (
                    coalesce_ingested_ranges,
                    get_eval_result_store,
                )

                store = get_eval_result_store(ws_path)
                for c in corpuses:
                    spans = coalesce_ingested_ranges(store.read_ranges(c["id"]))
                    ingested_by_id[c["id"]] = sum(end - start + 1 for start, end in spans)
        except Exception:
            log.warning(
                "⚠️ knowledge.eval — has_graph/ingested probe failed · track=%s · defaulting to empty",
                track,
                exc_info=True,
            )
        for c in corpuses:
            c["has_graph"] = group_for(c["id"]) in existing
            c["ingested_count"] = ingested_by_id.get(c["id"], 0)
        return _success(
            {"track": track, "folder": str(base), "corpuses": corpuses, "log_dir": log_dir}
        )
    except Exception as exc:
        log.error("knowledge eval corpuses list failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@eval_router.get("/eval/corpus")
async def eval_corpus(path: str = "") -> dict[str, Any]:
    """Load a memory-track corpus's episodes for the human-readable Corpus review panel.

    ``path`` is the ``<id>.episodes.jsonl`` for the chosen corpus (from the corpuses list).
    Returns each turn as ``{id, timestamp, speaker, type, body}`` in chronological order
    (``load_episodes_file`` sorts by timestamp), plus light meta (episode count + date span)
    for the stats header. Read-only and workspace-independent — episodes live beside their
    question banks. Memory-track only; knowledge corpora are folders of ``.md`` docs."""
    from hirocli.services.knowledge.graph.graphiti_corpus import load_episodes_file

    try:
        cpath = Path(path.strip())
        if not path.strip() or not cpath.exists():
            return envelope_failure(f"Corpus not found: {path or '(none given)'}")
        # Parsing reads + validates the whole file; keep it off the event loop.
        episodes = await run_in_threadpool(load_episodes_file, cpath)
        rows = [
            {
                "id": ep.chunk_id,
                "timestamp": ep.reference_time.isoformat() if ep.reference_time else "",
                "speaker": ep.speaker or "",
                "type": ep.source or "text",
                "body": ep.text,
            }
            for ep in episodes
        ]
        return _success(
            {
                "path": str(cpath),
                "episode_count": len(rows),
                # Episodes are already chronological → first/last bound the corpus date span.
                "first_timestamp": rows[0]["timestamp"] if rows else "",
                "last_timestamp": rows[-1]["timestamp"] if rows else "",
                "episodes": rows,
            }
        )
    except Exception as exc:
        log.error("knowledge eval corpus load failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@eval_router.get("/eval/corpus-extraction")
async def eval_corpus_extraction(
    workspace_id: SelectedWorkspaceIdDep,
    corpus_id: str = "",
) -> dict[str, Any]:
    """Per-episode at-ingest extraction summary for a memory corpus, for the Corpus-review tab.

    Returns ``{episodes: {<episode_id>: {entity_count, fact_count, run_id, step_index}}}`` built
    from the corpus's ingest-trace sidecars in the SELECTED workspace (where the eval ran). Lets the
    tab show whether each turn extracted anything and link straight to its ingest-pipeline trace.
    Empty ``{}`` when the corpus was ingested with graph tracing off (``observability != "trace"``)
    or hasn't been remembered yet — the tab then just omits the per-episode counts/button."""
    from hirocli.services.knowledge.graph.group_scope import eval_memory_group_id
    from hirocli.services.knowledge.graph.ingest_trace import read_group_ingest_extraction

    try:
        cid = corpus_id.strip()
        if not cid:
            return envelope_failure("corpus_id is required")
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path).resolve()
        group_id = eval_memory_group_id(cid)
        # Sidecar scan is plain file IO (no Kuzu lock) — keep it off the event loop.
        episodes = await run_in_threadpool(
            read_group_ingest_extraction, workspace_path, group_id
        )
        # group_id is returned so the Corpus tab can deep-link an episode into the graph view
        # (which filters by group + chunk_id) without re-deriving the eval-group naming client-side.
        return _success({"episodes": episodes, "group_id": group_id})
    except Exception as exc:
        log.error("knowledge eval corpus extraction failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@eval_router.get("/eval/questions")
async def eval_questions(path: str = "") -> dict[str, Any]:
    """List a corpus's question bank for the checklist (id/category/subcategory/text/gold).

    ``path`` is the ``<id>.questions.yaml`` for the chosen corpus (from the corpuses list).
    Workspace-independent — banks live beside their corpora."""
    from hirocli.services.eval.runner import load_questions

    try:
        qpath = Path(path.strip())
        if not path.strip() or not qpath.exists():
            return envelope_failure(f"Question bank not found: {path or '(none given)'}")
        rows = load_questions(qpath)
        questions = [
            {
                "id": q["id"],
                "category": q.get("category", ""),
                "subcategory": q.get("subcategory", ""),
                # Authored difficulty — surfaced as a chip in the question-picker checklist.
                "difficulty": q.get("difficulty", ""),
                "question": q["question"],
                "requires_graph": bool(q.get("requires_graph")),
                "expected_answer": q.get("expected_answer", ""),
            }
            for q in rows
        ]
        return _success({"path": str(qpath), "questions": questions})
    except Exception as exc:
        log.error("knowledge eval questions list failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))
