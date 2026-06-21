"""Memory-track eval runner.

Remembers a turn corpus into an eval-scoped ``eval_mem_{set}`` drawer (serial,
chronological), then recalls per question (recall → answer → judge) with a bounded
parallel question phase. Single recall leg, no flat/graph gate. Persists per-corpus
results via the store; publishes the shared ``eval.*`` events with
``track="memory"``.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hiro_commons.log import Logger

from hirocli.domain.events import get_domain_event_bus
from hirocli.runtime.agent_graph.tracing import traced_run
from hirocli.services.knowledge.constants import KNOWLEDGE_GRAPH_INGEST_COMPLETED

from hirocli.services.eval.constants import (
    EVAL_COMPLETED,
    EVAL_FAILED,
    EVAL_QUESTION_COMPLETED,
    EVAL_SETUP_PROGRESS,
    EVAL_STARTED,
)
from hirocli.services.knowledge.converters import utc_now_iso
from hirocli.services.knowledge.graph.group_scope import (
    eval_memory_group_id,
    slug_group_part,
)

from hirocli.services.eval.corpus import (
    ADAM_CORPUS_FILE,
    DEFAULT_MEMORY_EVAL_SET,
    MEMORY_EVAL_USER_ID,
    load_adam_questions,
)
from hirocli.services.eval.events import _cancel_requested, _preview, _publish
from hirocli.services.eval.models import build_eval_answer_model, build_eval_judge_model
from hirocli.services.eval.summary import summarize_memory_rows

if TYPE_CHECKING:
    from hirocli.services.eval.judge import RecallRenderOptions
    from hirocli.services.eval.locomo import EvidenceRecallContext

log = Logger.get("SVC.KNOWLEDGE.EVAL")


def _record_ingested_range(
    workspace_path: Path, set_id: str, start: int, count: int, cost_usd: float = 0.0
) -> None:
    """Persist that a remember batch ingested ``count`` episodes from ``start`` at ``cost_usd``
    (for the panel's ingested-range readout + the CUMULATIVE per-corpus ingest cost — the only
    place ingest cost survives a reload). Best-effort — a store hiccup must never abort the run."""
    if count <= 0:
        return
    try:
        from hirocli.services.eval.store import get_eval_result_store

        get_eval_result_store(Path(workspace_path)).append_range(
            set_id, int(start), int(count), float(cost_usd or 0.0)
        )
    except Exception:
        log.warning(
            "⚠️ knowledge.eval — failed to record ingested range · set=%s · [%s:+%s]",
            set_id,
            start,
            count,
            exc_info=True,
        )


def _reset_ingested_ranges(workspace_path: Path, set_id: str) -> None:
    """Drop the corpus's ingested-range records — called in lock-step with a graph wipe so the
    printed range can never outlive the data. Best-effort (never breaks the run)."""
    try:
        from hirocli.services.eval.store import get_eval_result_store

        get_eval_result_store(Path(workspace_path)).clear_ranges(set_id)
    except Exception:
        log.warning(
            "⚠️ knowledge.eval — failed to reset ingested ranges · set=%s",
            set_id,
            exc_info=True,
        )


async def _remember_episodes(
    memory: Any,
    episodes: "list[Any]",
    *,
    workspace_path: Path,
    run_id: str,
    user_id: int,
    character_id: str,
    episode_offset: int = 0,
    ledger_sink: Any | None = None,
) -> int:
    """Replay each episode through the ``remember`` path (one turn at a time, in
    chronological order so supersession resolves correctly). Emits a per-episode
    ``setup_progress`` line so the admin terminal ticks during the (LLM-bound) build.

    ``ledger_sink`` makes each turn's Graphiti extraction observable in **Graph Runs**:
    the caller opens one parent run (``current_run``) and passes its sink here, so every
    turn's per-episode/per-operation rows NEST under that single run (priced sub-rows fold
    into its aggregate). ``None`` ⇒ no ledger. Returns the facts learned across all turns."""
    bus = get_domain_event_bus()
    total = len(episodes)
    # Absolute 1-based episode numbers for the activity readout (offset is the 0-based start of
    # this batch's slice): the FIRST episode of the window is offset+1, the LAST is offset+total.
    # The panel shows these real episode numbers (e.g. "episode 11"), NOT a window-relative 1/N
    # counter that misleads when a batch starts partway through the corpus.
    first_no = int(episode_offset) + 1
    last_no = int(episode_offset) + total
    _publish(
        bus,
        workspace_path,
        EVAL_SETUP_PROGRESS,
        {
            "run_id": run_id,
            "phase": "remember",
            "episode_count": total,
            "from": first_no if total else 0,
            "to": last_no if total else 0,
        },
    )
    learned = 0
    for index, ep in enumerate(episodes, start=1):
        ref = getattr(ep, "reference_time", None)
        meta = {
            "timestamp": ref.isoformat() if ref is not None else "",
            "speaker": getattr(ep, "speaker", "") or "User",
            "message_id": getattr(ep, "chunk_id", "") or "",
        }
        result = await memory.add(
            ep.text,
            user_id=user_id,
            run_id=f"eval:{run_id}",
            character_id=character_id,
            metadata=meta,
            ledger_sink=ledger_sink,
            # Number each turn's LangSmith ingest tree so they read graph_ingest_1, _2, … under
            # the ingestion root (instead of N identical "graph_ingest" siblings).
            trace_label=f"graph_ingest_{index}",
            # Defer the Kuzu FTS rebuild: rebuilding per episode forces a CHECKPOINT each turn,
            # which stalls until every concurrent graph READ (the Graph-tab live export) leaves —
            # the "Timeout waiting for active transactions before checkpointing" freeze. We rebuild
            # ONCE after the loop instead (matches the knowledge ingest batch's end-of-batch rebuild).
            rebuild_fts=False,
        )
        learned += int(getattr(result, "stored_count", 0) or 0)
        _publish(
            bus,
            workspace_path,
            EVAL_SETUP_PROGRESS,
            {
                "run_id": run_id,
                "phase": "remember",
                "index": index,
                "total": total,
                # Absolute 1-based episode number (offset + this turn's 1-based position in the
                # window) so the line reads "episode 11", not a window-relative "1/20".
                "episode_no": int(episode_offset) + index,
                "snippet": _preview(ep.text, 90),
            },
        )
    # All turns written with rebuild_fts=False above → rebuild the keyword index ONCE now, so
    # keyword search + dedup see this batch (one Kuzu checkpoint instead of one per episode).
    # NON-FATAL: the turns are ALREADY committed to the graph. A failed FTS rebuild (e.g. the
    # checkpoint still racing a concurrent reader after retries) only leaves the keyword index
    # stale until the next graph open — initialize() rebuilds it. Aborting here would mark a
    # fully-ingested (paid-for) batch FAILED and skip the ingested-range record, so a re-run would
    # duplicate. Warn loudly and continue. (CancelledError is a BaseException → still propagates.)
    if episodes:
        try:
            await memory.flush_search_index()
        except Exception:
            log.warning(
                "⚠️ knowledge.eval — FTS rebuild after remember failed; turns are committed, "
                "keyword index refreshes on next graph open · run_id=%s",
                run_id,
                exc_info=True,
            )
    return learned


async def _recall_via_agent(
    *,
    question: str,
    memory: Any,
    workspace_path: Path,
    answer_model: Any | None,
    user_id: int,
    character_id: str,
    retrieval_limits: Any | None = None,
    retrieval_prompt_text: str = "",
) -> tuple[list[dict[str, Any]], list[str], Any | None]:
    """Run the agentic recall leg (P5): retrieval loop → reduce → legacy recall rows.

    ``retrieval_limits`` and ``retrieval_prompt_text`` are pre-resolved by ``run_memory_eval``
    once per run and threaded through to avoid reloading ``preferences.json`` on every
    parallel question. When either is omitted (direct ``_memory_question`` test entry, etc.)
    this function loads them from the workspace as a fallback.
    """
    from hirocli.services.memory.agent.reduce import apply_reduce, accumulated_item_to_recall_row
    from hirocli.services.memory.agent.retrieval_agent import run_retrieval

    limits = retrieval_limits
    prompt_text = retrieval_prompt_text
    if limits is None or not prompt_text:
        from hirocli.domain.preferences import load_preferences, resolve_retrieval_agent_prompt

        prefs = load_preferences(workspace_path)
        if limits is None:
            limits = prefs.graph.eval.retrieval_agent
        if not prompt_text:
            _prompt_id, prompt_text = resolve_retrieval_agent_prompt(prefs)

    retrieval_model = answer_model
    if retrieval_model is None:
        # Direct-call tests pass answer_model=None and rely on the monkey-patched eval model
        # builder; production always threads a built model in, so this path is a fallback.
        from hirocli.services.eval.models import build_eval_answer_model

        retrieval_model, _ = build_eval_answer_model(workspace_path)

    if retrieval_model is None:
        log.warning(
            "⚠️ knowledge.eval — retrieval agent skipped · no chat model · q=%s",
            _preview(question, 80),
        )
        return [], [], None

    result = await run_retrieval(
        question=question,
        memory=memory,
        limits=limits,
        prompt_text=prompt_text,
        model=retrieval_model,
        user_id=user_id,
        character_id=character_id,
    )
    reduced = apply_reduce(
        result.accumulator,
        op=result.reduce_op,
        args=result.reduce_args,
    )
    recalled_rows = [accumulated_item_to_recall_row(item) for item in reduced.items]
    facts = [str(r["memory"]) for r in recalled_rows if str(r.get("memory") or "").strip()]
    log.info(
        "⬇️ knowledge.eval — recall · items=%d · reduce=%s · q='%s'",
        len(recalled_rows),
        result.reduce_op,
        _preview(question, 80),
    )
    return recalled_rows, facts, result


def _persist_retrieval_trace(
    *,
    workspace_path: Path,
    run_id: str,
    question_id: str,
    retrieval_result: Any | None,
) -> None:
    """Write the agent-loop transcript sidecar (P6) — best-effort, never raises."""
    if retrieval_result is None:
        return
    transcript = getattr(retrieval_result, "transcript", None) or []
    if not transcript:
        return
    from hirocli.services.memory.agent.agent_trace import write_agent_retrieval_trace

    write_agent_retrieval_trace(
        workspace_path,
        run_id=run_id,
        question_id=question_id,
        events=transcript,
    )


def _memory_recall_output_preview(
    retrieval_result: Any | None,
    *,
    facts: list[str],
) -> str:
    """Ledger preview for the ``memory_recall`` node (P6)."""
    from hirocli.services.knowledge.ledger_runner import preview_answer
    from hirocli.services.memory.agent.agent_trace import format_memory_recall_output_preview

    facts_preview = preview_answer(" | ".join(facts) or "(nothing recalled)")
    if retrieval_result is None:
        return facts_preview
    return format_memory_recall_output_preview(
        getattr(retrieval_result, "transcript", None) or [],
        reduce_op=str(getattr(retrieval_result, "reduce_op", None) or "none"),
        facts_preview=facts_preview,
    )


async def _memory_question(
    memory: Any,
    q: dict[str, Any],
    *,
    workspace_path: Path,
    user_id: int,
    character_id: str,
    sink: Any | None = None,
    run_id: str = "",
    set_id: str = "",
    # Answer + judge use SEPARATE eval models (each its own model + tuning profile). Either may be
    # None (unconfigured/unavailable) → that step is skipped.
    answer_model: Any | None = None,
    answer_model_id: str = "",
    judge_model: Any | None = None,
    judge_model_id: str = "",
    judge: bool = False,
    # Renamed from answer_system_prompt: the answering instructions now ride in the USER message
    # (judge.answer_from_context); the system prompt there is a hardcoded role.
    answer_instructions: str = "",
    judge_system_prompt: str = "",
    render: "RecallRenderOptions | None" = None,
    retrieval_limits: Any | None = None,
    retrieval_prompt_text: str = "",
) -> dict[str, Any]:
    """One memory question, all in ONE Graph Run: **recall** (graph search) → **answer**
    (grounded only in the recalled facts) → optional **judge** (vs the ideal answer).

    The run holds a ``memory_recall`` node (graph-search spans), an ``eval_answer`` node, and an
    ``eval_judge`` node — all priced. Returns the unified row (``legs={'recall': {...}}`` with the
    model answer + verdict mark + recalled facts, plus ``gold``)."""
    from hirocli.runtime.agent_graph.ledger import RunAccumulator, current_entry, current_run
    from hirocli.services.eval.judge import (
        RecallRenderOptions,
        answer_from_context,
        judge_answer,
    )
    from hirocli.services.knowledge.ledger_runner import preview_query

    render = render or RecallRenderOptions()

    gold = q.get("expected_answer", "")
    is_control = str(q.get("expected_kind") or "") == "abstain"

    acc = None
    run_token = None
    if sink is not None:
        acc = RunAccumulator(
            sink=sink,
            run_id=f"memory_eval_q-{slug_group_part(set_id)}-{run_id}-{slug_group_part(str(q.get('id') or ''))}",
            inbound_id=eval_memory_group_id(set_id),
            character_id=set_id,
        )
        run_token = current_run.set(acc)

    facts: list[str] = []
    recalled_rows: list[dict[str, Any]] = []
    retrieval_result: Any | None = None
    answer, mark, reason, evidence = "", "", "", ""
    # Judge-reported: did the recalled context contain what was needed to answer? Defaults True
    # (judge off / not asked) so it never falsely flags a recall miss when unjudged.
    recall_sufficient = True
    grounded = True
    cost_usd = 0.0
    t0 = time.perf_counter()
    try:
        # 1) recall (graph search) — its own LangSmith ``recall`` span so the per-lane rerank(s)
        # + query-embedding group under it; ledgered as a memory_recall node when a sink present.
        with traced_run("recall", inputs={"question": q["question"]}) as _recall_rt:
            if sink is not None:
                # captures={"usage","decision"} is REQUIRED: without it to_row() blanks the recall
                # node's usage block (model/tokens), so its folded reranker/search cost was lost and
                # the per-question total under-counted (showed $0 when recall was the only priced
                # leg). Mirrors eval_answer/eval_judge (_ledger_llm_node) and the ingest nodes.
                entry = sink.open_entry(
                    "memory_recall", {}, None, captures=frozenset({"usage", "decision"})
                )
                entry_token = current_entry.set(entry)
                try:
                    recalled_rows, facts, retrieval_result = await _recall_via_agent(
                        question=q["question"],
                        memory=memory,
                        workspace_path=workspace_path,
                        answer_model=answer_model,
                        user_id=user_id,
                        character_id=character_id,
                        retrieval_limits=retrieval_limits,
                        retrieval_prompt_text=retrieval_prompt_text,
                    )
                    _persist_retrieval_trace(
                        workspace_path=workspace_path,
                        run_id=run_id,
                        question_id=str(q.get("id") or ""),
                        retrieval_result=retrieval_result,
                    )
                    entry.input_preview = preview_query(q["question"])
                    entry.output_preview = _memory_recall_output_preview(
                        retrieval_result,
                        facts=facts,
                    )
                finally:
                    entry.finish("ok")
                    sink.write_rows(entry.rows(include_parent=True))
                    current_entry.reset(entry_token)
            else:
                recalled_rows, facts, retrieval_result = await _recall_via_agent(
                    question=q["question"],
                    memory=memory,
                    workspace_path=workspace_path,
                    answer_model=answer_model,
                    user_id=user_id,
                    character_id=character_id,
                    retrieval_limits=retrieval_limits,
                    retrieval_prompt_text=retrieval_prompt_text,
                )
                _persist_retrieval_trace(
                    workspace_path=workspace_path,
                    run_id=run_id,
                    question_id=str(q.get("id") or ""),
                    retrieval_result=retrieval_result,
                )
            if _recall_rt is not None:
                _recall_rt.outputs = {
                    "recalled": len(recalled_rows),
                    "facts": sum(1 for h in recalled_rows if (h.get("kind") or "fact") == "fact"),
                    "entities": sum(1 for h in recalled_rows if h.get("kind") == "entity"),
                    "episodes": sum(1 for h in recalled_rows if h.get("kind") == "episode"),
                }
        # 2) answer — grounded ONLY in the recalled context (structured: facts/entities/episodes).
        if answer_model is not None:
            answer = await answer_from_context(
                answer_model,
                answer_model_id,
                question=q["question"],
                context=recalled_rows,
                sink=sink,
                # Editable graph.eval.memory_answer_prompt (blank → structured default in judge).
                instructions=answer_instructions,
                render=render,
            )
        # 3) judge — vs the ideal answer (optional step). Gets the SAME recalled context so it can
        # set recall_sufficient (recall-miss vs answering-miss), not just grade vs the ideal. Uses
        # the SEPARATE judge model (not the answer model).
        if judge and judge_model is not None:
            verdict = await judge_answer(
                judge_model,
                judge_model_id,
                question=q["question"],
                answer=answer,
                expected_answer=gold,
                context=recalled_rows,
                is_negative_control=is_control,
                sink=sink,
                system_prompt=judge_system_prompt,
                render=render,
            )
            mark, reason = verdict.mark, verdict.reason
            recall_sufficient = verdict.recall_sufficient
            grounded = verdict.grounded
            evidence = verdict.evidence
        if sink is not None and acc is not None:
            sink.write_run_row(
                acc,
                status="completed",
                decision_kind="completed",
                decision_detail="memory_eval_question",
                input_preview=f"q: {q['question'][:160]}",
                output_preview=(answer or " | ".join(facts))[:200],
            )
            # The per-question run accumulator folds recall + answer + judge node costs →
            # the whole question's LLM+reranker cost (read in-memory before evict).
            cost_usd = float(getattr(acc, "cost_usd", 0.0) or 0.0)
    finally:
        if run_token is not None and acc is not None:
            sink.evict_run(acc.run_id)
            current_run.reset(run_token)

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    recall_leg: dict[str, Any] = {
        "mode": "recall",
        "mark": mark,
        "reason": reason,
        "elapsed_ms": elapsed_ms,
        "answer": answer,
        "answer_preview": _preview(answer, 200),
        "run_id": (acc.run_id if acc is not None else None),
        "recalled": recalled_rows,
        "recall_sufficient": recall_sufficient,
        "grounded": grounded,
        "evidence": evidence,
        "cost_usd": cost_usd,
    }
    if retrieval_result is not None:
        from hirocli.services.memory.agent.agent_trace import build_retrieval_loop_payload

        limits = retrieval_limits
        if limits is None:
            from hirocli.domain.preferences import load_preferences

            limits = load_preferences(workspace_path).graph.eval.retrieval_agent
        loop_payload = build_retrieval_loop_payload(
            getattr(retrieval_result, "transcript", None) or [],
            reduce_op=str(getattr(retrieval_result, "reduce_op", None) or "none"),
            reduce_args=dict(getattr(retrieval_result, "reduce_args", None) or {}),
            max_agent_turns=int(getattr(limits, "max_agent_turns", 4) or 4),
        )
        if loop_payload is not None:
            recall_leg["retrieval_loop"] = loop_payload
    return {
        "id": q["id"],
        "category": q.get("category", ""),
        "subcategory": q.get("subcategory", ""),
        "difficulty": q.get("difficulty", ""),
        "question": q["question"],
        "requires_graph": bool(q.get("requires_graph")),
        "track": "memory",
        "gold": gold,
        "delta": "0",
        "cost_usd": cost_usd,
        # Negative control (expected_kind: abstain) — abstaining is correct here. Persisted in
        # row_json so the merged read-path summary scores abstains correctly too.
        "is_negative_control": is_control,
        # When this question finished evaluating (for the "Time" column). Persisted in row_json.
        "answered_at": utc_now_iso(),
        "legs": {
            "recall": recall_leg,
        },
    }


class _CancelRequestedInQuestion(Exception):
    """Cooperative-cancel sentinel raised inside a parallel question task.

    Deliberately NOT ``CancelledError``: ``asyncio.TaskGroup`` *ignores* cancelled
    children (that's how its quiet sibling-cancellation works), so a child raising
    ``CancelledError`` would let the run sail on to a bogus ``completed``. A plain
    ``Exception`` aborts the group; ``run_memory_eval`` translates it back to
    ``CancelledError`` so the route's terminal-cancel path is unchanged."""


def _unwrap_question_failure(eg: BaseExceptionGroup) -> BaseException:
    """Translate a question-phase ``TaskGroup`` failure into what the run's terminal
    paths expect.

    A cooperative-cancel sentinel anywhere in the group wins → ``CancelledError`` (the
    route then emits ``eval.cancelled``; cancel beats reporting a coincident
    failure the user no longer cares about). Otherwise unwrap to the first real child
    exception so the FAILED event carries its message instead of the group's opaque
    "unhandled errors in a TaskGroup"."""
    matched, rest = eg.split(_CancelRequestedInQuestion)
    if matched is not None:
        return asyncio.CancelledError()
    inner: BaseException = rest if rest is not None else eg
    while isinstance(inner, BaseExceptionGroup):
        inner = inner.exceptions[0]
    return inner


async def _memory_question_task(
    memory: Any,
    q: dict[str, Any],
    *,
    index: int,
    total: int,
    sem: asyncio.Semaphore,
    slots: list[dict[str, Any] | None],
    workspace_path: Path,
    rid: str,
    set_id: str,
    user_id: int,
    character_id: str,
    sink: Any,
    answer_model: Any | None,
    answer_model_id: str,
    judge_model: Any | None,
    judge_model_id: str,
    judged: bool,
    memory_answer_prompt: str,
    judge_prompt: str,
    render: "RecallRenderOptions",
    bus: Any,
    evidence_ctx: "EvidenceRecallContext | None" = None,
    retrieval_limits: Any | None = None,
    retrieval_prompt_text: str = "",
) -> None:
    """One question of the parallel phase: gate on the concurrency cap, run
    recall→answer→judge via ``_memory_question`` (unchanged — its per-question Graph Run
    accumulator and ledger contextvars are task-local, so parallel questions can't
    cross-attribute cost), store the row in its bank-order slot, and publish
    ``question_completed``. Runs under the ``asyncio.TaskGroup`` in ``run_memory_eval``.

    When ``evidence_ctx`` is set (LoCoMo corpus), score this question's evidence recall from its
    recalled context and attach it to the row, so the EV column + evidence fold populate LIVE
    instead of only on the post-run results refresh (the value matches the read path's, which
    recomputes it from the same sidecar)."""
    async with sem:
        # Cooperative cancel, checked as each question STARTS — queued questions never
        # run after a Cancel, mirroring the old serial loop's between-questions check.
        # Sentinel, not CancelledError: see _CancelRequestedInQuestion.
        if _cancel_requested(workspace_path, rid):
            log.info("🛑 knowledge.eval — cooperative cancel honored · run_id=%s", rid)
            raise _CancelRequestedInQuestion()
        # Align the eval_question span id with THIS question's per-question Graph Run row
        # (same formula _memory_question uses) so "open in LangSmith" links from the row.
        q_run_id = (
            f"memory_eval_q-{slug_group_part(set_id)}-{rid}-"
            f"{slug_group_part(str(q.get('id') or ''))}"
        )
        with traced_run(
            "eval_question",
            ledger_run_id=q_run_id,
            tags=["eval", "memory", str(q.get("category") or "")],
            metadata={"id": q.get("id")},
            inputs={"question": q.get("question", "")},
        ):
            row = await _memory_question(
                memory,
                q,
                workspace_path=workspace_path,
                user_id=user_id,
                character_id=character_id,
                sink=sink,
                run_id=rid,
                set_id=set_id,
                answer_model=answer_model,
                answer_model_id=answer_model_id,
                judge_model=judge_model,
                judge_model_id=judge_model_id,
                judge=judged,
                answer_instructions=memory_answer_prompt,
                judge_system_prompt=judge_prompt,
                render=render,
                retrieval_limits=retrieval_limits,
                retrieval_prompt_text=retrieval_prompt_text,
            )
    # Evidence recall (LoCoMo corpora): score X/Y gold-evidence coverage from THIS question's
    # recalled context and inline it on the row, so the live event carries it (EV column + fold
    # populate as rows stream, not only after the post-run refresh). Best-effort — a scoring
    # hiccup must never abort the question; the read path will still compute it later.
    if evidence_ctx is not None:
        try:
            recalled = ((row.get("legs") or {}).get("recall") or {}).get("recalled") or []
            ev = evidence_ctx.for_recalled(str(q.get("id") or ""), recalled)
            if ev is not None:
                row["evidence_recall"] = ev
        except Exception:
            log.warning(
                "⚠️ knowledge.eval — live evidence-recall scoring failed · qid=%s",
                q.get("id"),
                exc_info=True,
            )
    # Outside the semaphore: the slot write + event are cheap and must not hold a
    # concurrency ticket another question could be using.
    slots[index] = row
    _publish(
        bus,
        workspace_path,
        EVAL_QUESTION_COMPLETED,
        {"run_id": rid, "index": index, "total": total, **row},
    )


async def run_memory_eval(
    memory: Any,
    workspace_path: Path,
    *,
    set_id: str = DEFAULT_MEMORY_EVAL_SET,
    questions: list[dict[str, Any]] | None = None,
    episodes: "list[Any] | None" = None,
    corpus_path: Path | None = None,
    questions_path: Path | None = None,
    run_id: str | None = None,
    remember: bool = True,
    clear_before: bool = False,
    episode_offset: int = 0,
    episode_limit: int | None = None,
    judge: bool = False,
    answer_prompt_id: str | None = None,
    question_concurrency: int = 1,
    eval_user_id: int = MEMORY_EVAL_USER_ID,
) -> dict[str, Any]:
    """Run the memory-eval track: remember a turn corpus, then recall per question.

    Single engine (recall), no flat/graph comparison, no PROCEED/PIVOT gate (docs §8).
    Emits the shared ``eval.*`` events with a ``track="memory"`` discriminator
    so the existing registry/SSE/replay infra carries it unchanged. ``memory`` must be an
    **eval-scoped** facade (its writes/reads target ``eval_mem_{set}``); the caller owns
    its lifecycle (build + close).

    ``clear_before`` wipes the drawer up front (decoupled from ``remember`` so a corpus can be
    built across appended batches). ``episode_offset``/``episode_limit`` bound the remember phase
    to a contiguous slice of the (chronological) corpus, so a large corpus is built in monitored
    chunks. ``questions`` may be empty for a setup-only (remember/clear) batch.

    ``question_concurrency`` caps how many questions run their recall→answer→judge legs at
    once (1 = serial, the default; the route clamps to ``MAX_QUESTION_CONCURRENCY``). Only
    the QUESTION phase parallelizes — the remember phase stays strictly serial (chronological
    supersession + the Kuzu write lock both require it).

    Returns the summary payload (also published as ``eval.completed``)."""
    from hirocli.services.knowledge.graph.graphiti_corpus import load_episodes_file

    bus = get_domain_event_bus()
    rid = run_id or f"memeval-{uuid.uuid4()}"
    questions = questions if questions is not None else load_adam_questions()
    total = len(questions)
    # character_id is cosmetic for an eval-scoped facade (the override mints the drawer),
    # but the MemoryService API requires one; the set id is the natural label.
    character_id = set_id
    started_at = time.perf_counter()

    # One ledger sink for the whole eval → the remember/build shows as ONE Graph Run and each
    # recall shows as its own retrieve run, mirroring the knowledge track (ingest run + per-question
    # answer runs). Lazy import keeps the ledger off this module's base import path.
    from hirocli.runtime.agent_graph.ledger import LedgerSink, RunAccumulator, current_run

    sink = LedgerSink(workspace_path)
    # Answer + judge each use their OWN eval model/tuning (separated — graph.eval.answer_* vs
    # graph.eval.judge_*). The judge is only built when requested.
    answer_model, answer_model_id = build_eval_answer_model(workspace_path)
    judge_model, judge_model_id = (
        build_eval_judge_model(workspace_path) if judge else (None, "")
    )
    # Editable eval prompts (graph.eval.*); blank → relaxed defaults in judge.
    from hirocli.domain.preferences import load_preferences

    _prefs = load_preferences(workspace_path)
    _eval_prefs = _prefs.graph.eval
    # Resolve the run's chosen answer-prompt profile (eval-panel pick) → instruction text + a
    # provenance label; unknown/blank id falls back to the locked default profile, then the
    # built-in constant. The id alone can later resolve to different text (profiles are editable),
    # so a content hash is recorded on the run for reproducible "which prompt produced this".
    answer_prompt_label, memory_answer_prompt = _eval_prefs.resolve_answer_prompt(answer_prompt_id)
    answer_prompt_hash = hashlib.sha256(memory_answer_prompt.encode("utf-8")).hexdigest()[:8]
    judge_prompt = _eval_prefs.judge_prompt
    # Pre-resolve the retrieval-agent prefs ONCE per run and thread them into every question
    # task — avoids a load_preferences() disk read per parallel question (admin pref changes
    # mid-run land on the next run, same contract as answer/judge prompts).
    _retrieval_limits = _eval_prefs.retrieval_agent
    _, _retrieval_prompt_text = _eval_prefs.resolve_retrieval_agent_prompt()
    # Recalled-context render toggles (graph.eval.show_*) — built once and shared by every
    # question's answer/judge/evidence renders so they stay consistent within the run.
    from hirocli.services.eval.judge import RecallRenderOptions

    render = RecallRenderOptions(
        show_event_time=_eval_prefs.show_event_time,
        show_expired_at=_eval_prefs.show_expired_at,
        show_superseded=_eval_prefs.show_superseded,
    )
    judged = judge and judge_model is not None

    _publish(
        bus,
        workspace_path,
        EVAL_STARTED,
        {
            "run_id": rid,
            "total_questions": total,
            "track": "memory",
            "modes": ["recall"],
            "judged": judged,
            "filters": {"set": set_id},
            # Provenance: which answer-prompt profile drove this run's answers (label-tags the run
            # so two runs of the same corpus under different prompts are distinguishable; the hash
            # pins the exact text since profiles are editable). id="" ⇒ default profile used.
            "answer_prompt": {
                "id": (answer_prompt_id or "").strip(),
                "label": answer_prompt_label,
                "hash": answer_prompt_hash,
            },
        },
    )

    rows: list[dict[str, Any]] = []
    # TWO sibling LangSmith roots per corpus (no shared umbrella), so the build and the question
    # batch read as separate trees: ``memory_eval_{set}_ingestion`` (the remember leg) and
    # ``memory_eval_{set}_questions`` (the eval_question group). No-op when tracing is off.
    try:
        remembered = 0
        ingest_cost_usd = 0.0
        # The remember phase's ingest Graph Run id — surfaced to the panel so it can open the
        # ingest pipeline trace. Empty on a question-subset re-run (remember=False = no ingest).
        ingest_run_id = ""
        # Explicit, decoupled clear (batched-build support): wipe this eval set's graph drawer
        # ONLY when asked — NOT as a side effect of remember. This is what lets a large corpus be
        # built in appended batches (remember a range with clear_before=False) without each batch
        # wiping the last. A from-scratch rebuild = clear_before=True on the FIRST batch only.
        # Re-remembering the SAME turns over an existing graph lets Graphiti dedup/invalidate
        # against stale state, so clear when you mean to rebuild, not when you mean to append.
        # Eval-scoped facade ⇒ clear_all targets only the eval_mem_{set} drawer.
        if clear_before:
            cleared = await memory.clear_all(user_id=eval_user_id, character_id=character_id)
            # Reset the ingested-range record in the SAME breath as the graph wipe so the panel's
            # printed range never describes data that's no longer there (the agreed invariant).
            _reset_ingested_ranges(workspace_path, set_id)
            if cleared:
                log.info(
                    "🧹 knowledge.eval — memory clear · wiped %d prior fact(s) · set=%s",
                    cleared,
                    set_id,
                )
        if remember:
            eps = episodes if episodes is not None else load_episodes_file(
                corpus_path or ADAM_CORPUS_FILE
            )
            # Batch window: remember only episodes [offset : offset+limit] this run, so a large
            # corpus builds in monitored chunks (each batch's graph-build cost lands in the
            # summary). The corpus is chronologically sorted, so contiguous ranges run in order
            # across batches and supersession still resolves. offset past the end ⇒ empty slice ⇒
            # a no-op batch (remembers nothing), not an error.
            if episode_offset or episode_limit is not None:
                end = len(eps) if episode_limit is None else episode_offset + episode_limit
                eps = eps[episode_offset:end]
            # Open ONE parent run so every turn's Graphiti extraction nests under it (priced
            # sub-rows fold into the aggregate) — the memory "ingest" Graph Run.
            ledger_run_id = f"memory_eval-{slug_group_part(set_id)}-{rid}"
            ingest_run_id = ledger_run_id
            # Root 1 — INGESTION: its own LangSmith tree for the "remember" leg; every turn's
            # graph_ingest_{n}/add_episode span nests here. ledger_run_id aligns the span id with
            # the ingest Graph Run row (so "open in LangSmith" links from it). when=bool(eps): an
            # empty slice (no-op append batch / offset past the end) makes no add_episode calls, so
            # skip the span instead of posting a hollow ingestion tree to LangSmith.
            with traced_run(
                f"memory_eval_{set_id}_ingestion",
                when=bool(eps),
                ledger_run_id=ledger_run_id,
                tags=["eval", "memory", "ingest", f"set:{set_id}"],
                metadata={"set": set_id, "episode_count": len(eps)},
            ):
                accumulator = RunAccumulator(
                    sink=sink,
                    run_id=ledger_run_id,
                    inbound_id=eval_memory_group_id(set_id),
                    character_id=set_id,
                )
                token = current_run.set(accumulator)
                try:
                    remembered = await _remember_episodes(
                        memory,
                        eps,
                        workspace_path=workspace_path,
                        run_id=rid,
                        user_id=eval_user_id,
                        character_id=character_id,
                        episode_offset=episode_offset,
                        ledger_sink=sink,
                    )
                    # Ingest (graph build) cost — the remember run's folded LLM+reranker cost.
                    # Computed BEFORE recording the range so this batch's cost is persisted with it
                    # (the range row is the only durable home for ingest cost across reloads).
                    ingest_cost_usd = float(getattr(accumulator, "cost_usd", 0.0) or 0.0)
                    # Record THIS batch's episode window (offset + actual slice length) AND its
                    # ingest cost so the panel can print the ingested range + the cumulative
                    # per-corpus ingest spend. After clear_before reset above, batches accumulate;
                    # len(eps) is the true count (≤ requested limit at the tail).
                    _record_ingested_range(
                        workspace_path, set_id, episode_offset, len(eps), ingest_cost_usd
                    )
                    sink.write_run_row(
                        accumulator,
                        status="completed",
                        decision_kind="completed",
                        decision_detail="memory_eval_remember",
                        input_preview=f"corpus: {set_id} ({len(eps)} turns)",
                        output_preview=f"remembered {len(eps)} turns · learned {remembered} facts",
                    )
                    # Stream the ingest cost the moment the remember phase ends — emitted as a
                    # setup_progress line so the panel surfaces graph-build cost LIVE, instead of
                    # only when the terminal `completed` summary lands at run end. The remember
                    # phase is the priciest part and runs before any question row exists, so
                    # without this the cost UI showed nothing during ingestion.
                    _publish(
                        bus,
                        workspace_path,
                        EVAL_SETUP_PROGRESS,
                        {
                            "run_id": rid,
                            "phase": "remember_done",
                            "episode_count": len(eps),
                            "ingest_cost_usd": ingest_cost_usd,
                            # Lets the panel open the ingest pipeline trace for this remember run.
                            "ingest_run_id": ingest_run_id,
                        },
                    )
                    # Pair the per-turn graph ingest_progress events (emitted by the memory
                    # facade's graph event_sink) with ONE completion, scoped to this eval's
                    # group. Without it the Graph tab's "ingesting chunk N/M…" status had
                    # nothing to clear on the memory track and stuck until a manual refresh
                    # (only the knowledge routes emitted ingest_completed). One event per
                    # remember phase (not per turn) keeps the Graph tab's reconcile cheap.
                    _publish(
                        bus,
                        workspace_path,
                        KNOWLEDGE_GRAPH_INGEST_COMPLETED,
                        {"group_id": eval_memory_group_id(set_id)},
                    )
                finally:
                    sink.evict_run(ledger_run_id)
                    current_run.reset(token)
        # Root 2 — QUESTIONS: its own LangSmith tree; each question nests under it as an
        # ``eval_question`` span (recall → answer → judge). when=bool(questions): a setup-only
        # batch (remember/clear with no questions) nests nothing, so skip the empty root span.
        with traced_run(
            f"memory_eval_{set_id}_questions",
            when=bool(questions),
            ledger_run_id=rid,
            tags=["eval", "memory", "questions", f"set:{set_id}", f"judge:{judged}"],
            metadata={"total_questions": total, "set": set_id},
        ):
            # Parallel question phase (replaces the serial loop; no-backward-compat mode —
            # question_concurrency=1 reproduces it exactly). Every question is a task gated
            # by ONE shared semaphore; slot-per-index keeps bank order however completion
            # interleaves, so the summary/report tables are stable across caps. Tasks copy
            # their contextvars, so the eval_question spans still nest under the root above
            # and each question's Graph Run accumulator stays isolated.
            # Evidence-recall context (LoCoMo corpora): load the sidecar + episode bodies ONCE here
            # so each question can be scored as it completes and emit its X/Y live. None for a
            # non-LoCoMo corpus or when no questions_path was passed → questions emit no evidence
            # recall (the read path computes it post-run, as before). Best-effort: a load failure
            # must never abort the run.
            evidence_ctx = None
            if questions_path is not None and questions:
                try:
                    from hirocli.services.eval.locomo import (
                        load_evidence_recall_context,
                    )

                    evidence_ctx = load_evidence_recall_context(set_id, Path(questions_path))
                except Exception:
                    log.warning(
                        "⚠️ knowledge.eval — evidence-recall context load failed · set=%s",
                        set_id,
                        exc_info=True,
                    )
            slots: list[dict[str, Any] | None] = [None] * total
            sem = asyncio.Semaphore(max(1, int(question_concurrency)))
            try:
                async with asyncio.TaskGroup() as tg:
                    for index, q in enumerate(questions):
                        tg.create_task(
                            _memory_question_task(
                                memory,
                                q,
                                index=index,
                                total=total,
                                sem=sem,
                                slots=slots,
                                workspace_path=workspace_path,
                                rid=rid,
                                set_id=set_id,
                                user_id=eval_user_id,
                                character_id=character_id,
                                sink=sink,
                                answer_model=answer_model,
                                answer_model_id=answer_model_id,
                                judge_model=judge_model,
                                judge_model_id=judge_model_id,
                                judged=judged,
                                memory_answer_prompt=memory_answer_prompt,
                                judge_prompt=judge_prompt,
                                render=render,
                                bus=bus,
                                evidence_ctx=evidence_ctx,
                                retrieval_limits=_retrieval_limits,
                                retrieval_prompt_text=_retrieval_prompt_text,
                            )
                        )
            except BaseExceptionGroup as eg:
                # Re-raise as the single exception the terminal paths below expect
                # (CancelledError on cooperative cancel; the first real child error
                # otherwise) — never the group's opaque "unhandled errors" wrapper.
                raise _unwrap_question_failure(eg) from eg
            rows.extend(r for r in slots if r is not None)
    except Exception as exc:
        # CancelledError is a BaseException (not Exception) → it propagates past this
        # handler to the route's cancel path, exactly as run_eval relies on.
        log.error(
            "❌ knowledge.eval — memory run aborted",
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

    # Shared aggregate shape (also used by the persisted-results merged read), then
    # augment with this run's ingest-specific fields the merged snapshot can't carry:
    # remembered_turns, the real wall-clock elapsed, and the remember/graph-build cost.
    summary = summarize_memory_rows(rows, run_id=rid, judged=judged)
    summary["remembered_turns"] = remembered
    summary["elapsed_ms"] = int((time.perf_counter() - started_at) * 1000)
    # Cost (LLM + reranker; embeddings unpriced). Ingest = the remember/graph-build run;
    # questions = sum of per-question recall+answer+judge runs.
    summary["ingest_cost_usd"] = ingest_cost_usd
    summary["total_cost_usd"] = ingest_cost_usd + summary["questions_cost_usd"]
    # Carry the ingest Graph Run id so the panel's "Ingest pipeline" button can open its trace
    # (only set when this run actually remembered; a subset re-run leaves it empty → None).
    summary["ingest_run_id"] = ingest_run_id or None
    passing_recall = summary["passing"]["recall"]
    _publish(bus, workspace_path, EVAL_COMPLETED, summary)
    log.info(
        "✅ knowledge.eval — memory run complete · remembered=%d · recalled_for=%d/%d · "
        "judged=%s · pass=%d · cost=$%.4f (ingest $%.4f + Q $%.4f) · set=%s",
        summary["remembered_turns"],
        summary["recalled_for"],
        total,
        judged,
        passing_recall,
        summary["total_cost_usd"],
        summary["ingest_cost_usd"],
        summary["questions_cost_usd"],
        set_id,
    )
    return summary
