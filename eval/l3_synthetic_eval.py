"""L3 prototype — synthetic corpus eval harness.

The Phase 4 proceed-or-pivot gate: run the same set of personal-data
questions through ``knowledge_answer`` twice (``use_graph=False`` and
``use_graph=True``), score against expected substring fragments, and print
a side-by-side table.

USAGE
-----

    python eval/l3_synthetic_eval.py --workspace D:/path/to/workspace

Prerequisites (the harness will fail loud with a clear message if these
are missing — it does NOT silently degrade):

  * The workspace path must point at a real Hiro workspace (created via
    ``hiro workspaces create`` or equivalent) with ``preferences.json``.
  * ``knowledge.answering.model`` or ``llm.default_chat`` must be set to
    a catalog model id (e.g. ``openai:gpt-5-mini``) AND the matching
    provider key must be configured for the workspace.
  * The default knowledge embedder (FastEmbed MiniLM) downloads ~220MB on
    first use; no setup beyond ``uv sync`` needed.

This is a **manual / developer** harness — not part of the runtime. It
makes real LLM calls (one extraction call per chunk during ingest, one
rewrite + optionally one disambiguation per question), so it isn't free.
Budget: small corpus (~7 docs) → ~10–20 ingest LLM calls + 24 query LLM
calls (12 questions × 2 modes). Costs cents at gpt-5-mini scale.

The script is intentionally self-contained — no test runner, no fixtures
— so it can also serve as an executable smoke test for the whole L3
prototype path: ``knowledge_ingest`` → ``knowledge_graph_ingest`` →
``knowledge_answer`` with ``use_graph`` toggle + entity rewrite.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hirocli.domain.model_factory import create_chat_model
from hirocli.domain.preferences import (
    load_preferences,
    resolve_knowledge_graph_disambiguation_llm,
    resolve_knowledge_graph_extraction_llm,
)
from hirocli.services.knowledge import create_knowledge_service
from hirocli.services.knowledge.constants import (
    GRAPH_DIR,
    KNOWLEDGE_DIR,
    LADYBUG_DB_FILENAME,
)
# Phase 5c — the scoring + delta math moved into the package so the
# admin-UI Eval Batch runner and this CLI harness can't drift apart on the
# core gate logic. Re-exported below for backward compatibility with the
# pure-logic tests in test_l3_synthetic_eval.py.
from hirocli.services.knowledge.eval_scoring import (
    MARK_RANK as _MARK_RANK,  # noqa: F401 — re-export
    Score,                     # noqa: F401 — re-export
    delta_mark,                # noqa: F401 — re-export
    score_answer,              # noqa: F401 — re-export
)
from hirocli.services.knowledge.graph.ingest import (
    ChunkInput,
    GraphIngestService,
    make_llm_disambiguator,
)
from hirocli.services.knowledge.graph.ladybug_adapter import LadybugGraphStore

SYNTHETIC_CORPUS_DIR = Path(__file__).parent / "l3_synthetic"
QUESTIONS_FILE = Path(__file__).parent / "l3_questions.yaml"


# ---------------------------------------------------------------------------
# Setup — ingest the synthetic corpus + build the graph
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    document_ids: list[str] = field(default_factory=list)
    document_titles: dict[str, str] = field(default_factory=dict)


async def ingest_synthetic_corpus(service: Any) -> IngestResult:
    paths = sorted(SYNTHETIC_CORPUS_DIR.glob("*.md"))
    if not paths:
        raise RuntimeError(
            f"No .md files in {SYNTHETIC_CORPUS_DIR} — the eval corpus is missing."
        )
    print(f"  → {len(paths)} markdown files: {[p.name for p in paths]}")

    job = await service.ingest_and_wait(
        [str(p) for p in paths],
        owner_kind="system",
        owner_id="0",
    )
    # The job result holds totals; document ids are not on the result object,
    # so list documents fresh to get ids + titles for the graph-ingest step.
    docs_result = await service.list_documents(limit=200, offset=0)
    res = IngestResult()
    for doc in docs_result.documents:
        # Only include the synthetic-corpus docs (filter by source_uri prefix).
        if str(doc.source_uri).startswith(str(SYNTHETIC_CORPUS_DIR)):
            res.document_ids.append(doc.id)
            res.document_titles[doc.id] = doc.title or ""
    if not res.document_ids:
        raise RuntimeError(
            "Knowledge ingest returned no documents matching the synthetic corpus path. "
            f"Job totals: requested={job.totals.get('requested')} "
            f"ingested={job.totals.get('ingested')} skipped={job.totals.get('skipped')} "
            f"failed={job.totals.get('failed')}"
        )
    print(f"  → ingested {len(res.document_ids)} document(s) into Qdrant")
    return res


async def build_graph_from_corpus(
    service: Any,
    workspace_path: Path,
    ingested: IngestResult,
) -> None:
    """Construct the Ladybug graph by running graph extraction on every chunk
    of every ingested synthetic-corpus document. Uses the same code path the
    ``knowledge_graph_ingest`` Tool uses; bypassing the Tool only to keep the
    eval workspace-name-free."""
    prefs = load_preferences(workspace_path)
    extraction = resolve_knowledge_graph_extraction_llm(prefs, workspace_path)
    if extraction is None:
        raise RuntimeError(
            "knowledge_graph_ingest: no extraction model configured. "
            "Set knowledge.answering.model (or llm.default_chat) and ensure "
            "the provider key is in the workspace credential store."
        )
    extract_model = create_chat_model(
        extraction.model_id,
        workspace_path=workspace_path,
        temperature=extraction.temperature,
        max_tokens=extraction.max_tokens,
        thinking=extraction.thinking,
    )
    disambig = resolve_knowledge_graph_disambiguation_llm(prefs, workspace_path)
    disambiguator = None
    if disambig is not None:
        disambig_model = create_chat_model(
            disambig.model_id,
            workspace_path=workspace_path,
            temperature=disambig.temperature,
            max_tokens=disambig.max_tokens,
            thinking=disambig.thinking,
        )
        disambiguator = make_llm_disambiguator(disambig_model)

    graph_db_path = (
        workspace_path / KNOWLEDGE_DIR / GRAPH_DIR / LADYBUG_DB_FILENAME
    )
    store = LadybugGraphStore.open(graph_db_path)
    try:
        graph_svc = GraphIngestService(store, workspace_path=workspace_path)
        for doc_id in ingested.document_ids:
            detail = await service.get_document(doc_id, chunk_limit=200)
            chunks: list[ChunkInput] = []
            for raw in detail.chunks:
                text = str(raw.get("text") or "").strip()
                point_id = str(raw.get("point_id") or "")
                if not text or not point_id:
                    continue
                chunks.append(
                    ChunkInput(chunk_id=point_id, document_id=doc_id, text=text)
                )
            if not chunks:
                continue
            title = ingested.document_titles.get(doc_id, "")
            print(f"  → graph-ingest: {title!r} ({len(chunks)} chunks)")
            stats = await graph_svc.ingest_chunks(
                chunks,
                source_role="user_document",
                model=extract_model,
                disambiguator=disambiguator,
                document_id=doc_id,
                document_title=title,
            )
            print(
                f"     · created={stats.entities_created}"
                f" linked={stats.entities_linked_exact + stats.entities_linked_fuzzy + stats.entities_linked_llm}"
                f" edges={stats.edges_written}"
                f" llm_calls={stats.llm_extraction_calls + stats.llm_disambiguation_calls}"
                f" tokens={stats.total_input_tokens}i/{stats.total_output_tokens}o"
            )
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Run questions side-by-side
# ---------------------------------------------------------------------------


@dataclass
class QuestionRow:
    id: str
    category: str
    question: str
    requires_graph: bool
    off_score: Score
    off_elapsed_ms: float
    off_answer: str
    on_score: Score
    on_elapsed_ms: float
    on_answer: str

    @property
    def delta(self) -> str:
        return delta_mark(self.off_score, self.on_score)


async def ask_one(service: Any, question_text: str, *, use_graph: bool) -> tuple[Any, float]:
    t0 = time.perf_counter()
    result = await service.answer(
        question_text,
        rewrite=True,       # entities[] is what graph_expand consumes
        use_graph=use_graph,
    )
    return result, (time.perf_counter() - t0) * 1000.0


async def run_questions(service: Any, questions: list[dict[str, Any]]) -> list[QuestionRow]:
    rows: list[QuestionRow] = []
    for q in questions:
        qid = str(q.get("id") or "?")
        qtext = str(q.get("question") or "").strip()
        if not qtext:
            print(f"  ⚠ skipping question {qid!r}: empty question text")
            continue
        expected = [str(f) for f in (q.get("expected_fragments") or [])]
        category = str(q.get("category") or "")
        requires_graph = bool(q.get("requires_graph"))

        # graph-off
        off_result, off_elapsed = await ask_one(service, qtext, use_graph=False)
        off_score = score_answer(
            off_result.answer or "", expected, no_results=bool(off_result.no_results)
        )

        # graph-on
        on_result, on_elapsed = await ask_one(service, qtext, use_graph=True)
        on_score = score_answer(
            on_result.answer or "", expected, no_results=bool(on_result.no_results)
        )

        rows.append(
            QuestionRow(
                id=qid,
                category=category,
                question=qtext,
                requires_graph=requires_graph,
                off_score=off_score,
                off_elapsed_ms=off_elapsed,
                off_answer=off_result.answer or "",
                on_score=on_score,
                on_elapsed_ms=on_elapsed,
                on_answer=on_result.answer or "",
            )
        )
        # Per-question line for live progress.
        gate = "▲" if requires_graph else " "
        print(
            f"  {gate} [{qid:28s}] off {off_score.mark} ({off_elapsed:5.0f}ms)"
            f"  on {on_score.mark} ({on_elapsed:5.0f}ms)  Δ {rows[-1].delta}"
        )
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def render_table(rows: list[QuestionRow]) -> str:
    """A markdown-style side-by-side table — matches plan §5.6 / Example F."""
    headers = ["▲", "id", "category", "question", "flat", "graph", "Δ"]
    body: list[list[str]] = []
    for r in rows:
        body.append([
            "▲" if r.requires_graph else "",
            r.id,
            _truncate(r.category, 28),
            _truncate(r.question, 56),
            r.off_score.mark,
            r.on_score.mark,
            r.delta,
        ])
    widths = [max(len(c) for c in col) for col in zip(headers, *body)] if body else [len(h) for h in headers]
    sep_row = [w * "-" for w in widths]
    lines = [
        " | ".join(h.ljust(w) for h, w in zip(headers, widths)),
        "-+-".join(sep_row),
    ]
    for row in body:
        lines.append(" | ".join(c.ljust(w) for c, w in zip(row, widths)))
    return "\n".join(lines)


def render_summary(rows: list[QuestionRow]) -> str:
    """The proceed-or-pivot gate, distilled."""
    if not rows:
        return "no rows"

    def counts(getter) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in rows:
            out[getter(r).mark] = out.get(getter(r).mark, 0) + 1
        return out

    off = counts(lambda r: r.off_score)
    on = counts(lambda r: r.on_score)
    requires = [r for r in rows if r.requires_graph]
    on_wins = sum(1 for r in rows if _MARK_RANK[r.on_score.mark] > _MARK_RANK[r.off_score.mark])
    on_loses = sum(1 for r in rows if _MARK_RANK[r.on_score.mark] < _MARK_RANK[r.off_score.mark])
    ties = len(rows) - on_wins - on_loses

    requires_off_pass = sum(
        1 for r in requires if r.off_score.mark in ("✓", "🛇")
    )
    requires_on_pass = sum(
        1 for r in requires if r.on_score.mark in ("✓", "🛇")
    )

    lines = [
        "",
        f"questions: {len(rows)} total · requires_graph={len(requires)}",
        f"  flat:  ✓={off.get('✓',0)} ◐={off.get('◐',0)} ✗={off.get('✗',0)} 🛇={off.get('🛇',0)}",
        f"  graph: ✓={on.get('✓',0)} ◐={on.get('◐',0)} ✗={on.get('✗',0)} 🛇={on.get('🛇',0)}",
        f"  delta: graph wins={on_wins} · ties={ties} · graph loses={on_loses}",
        "",
        f"requires_graph subset ({len(requires)}):",
        f"  flat passing:  {requires_off_pass}/{len(requires)}",
        f"  graph passing: {requires_on_pass}/{len(requires)}",
        "",
        "GATE — thesis holds if `graph passing > flat passing` on the requires_graph subset.",
        f"       result: graph={requires_on_pass} flat={requires_off_pass}"
        f"  →  {'✅ PROCEED' if requires_on_pass > requires_off_pass else '❌ PIVOT'}",
    ]
    return "\n".join(lines)


def render_failures_detail(rows: list[QuestionRow]) -> str:
    """For any question where flat ≠ graph, show both answers so failures
    are traceable without re-running. Trim long answers."""
    lines: list[str] = ["", "--- diff (rows where flat ≠ graph) ---"]
    diffs = [r for r in rows if _MARK_RANK[r.off_score.mark] != _MARK_RANK[r.on_score.mark]]
    if not diffs:
        lines.append("  (none — both modes scored identically on every question)")
        return "\n".join(lines)
    for r in diffs:
        lines.append("")
        lines.append(f"[{r.id}] {r.question}")
        lines.append(f"  flat  ({r.off_score.mark}): {_truncate(r.off_answer, 220)}")
        lines.append(f"  graph ({r.on_score.mark}): {_truncate(r.on_answer, 220)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="L3 prototype eval — synthetic corpus, flat vs graph-augmented retrieval.",
    )
    p.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="Absolute path to a Hiro workspace with LLM providers configured.",
    )
    p.add_argument(
        "--skip-ingest",
        action="store_true",
        help=(
            "Skip the knowledge + graph ingest steps and only run questions. "
            "Use when the workspace is already populated with the synthetic corpus."
        ),
    )
    p.add_argument(
        "--show-answers",
        action="store_true",
        help="Print full answer text (not just the diff) for every question.",
    )
    return p.parse_args(argv)


async def amain(args: argparse.Namespace) -> int:
    workspace_path = args.workspace.resolve()
    if not workspace_path.exists():
        print(f"❌ workspace path does not exist: {workspace_path}", file=sys.stderr)
        return 2
    print(f"workspace: {workspace_path}")

    service = create_knowledge_service(workspace_path)

    try:
        if not args.skip_ingest:
            print("\n[1/3] Ingesting synthetic corpus → Qdrant ...")
            ingested = await ingest_synthetic_corpus(service)
            print("\n[2/3] Building entity/relationship graph → LadybugDB ...")
            await build_graph_from_corpus(service, workspace_path, ingested)
        else:
            print("\n[1–2/3] Skipping ingest (--skip-ingest).")

        print("\n[3/3] Loading questions ...")
        questions = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
        if not isinstance(questions, list) or not questions:
            print(f"❌ {QUESTIONS_FILE} is empty or malformed", file=sys.stderr)
            return 2

        print(f"\n     running {len(questions)} question(s) × 2 modes (flat / graph) ...")
        rows = await run_questions(service, questions)

        print("\n" + render_table(rows))
        print(render_summary(rows))
        if args.show_answers:
            print("\n--- full answers ---")
            for r in rows:
                print(f"\n[{r.id}] {r.question}")
                print(f"  flat  ({r.off_score.mark}, {r.off_elapsed_ms:.0f}ms): {r.off_answer}")
                print(f"  graph ({r.on_score.mark}, {r.on_elapsed_ms:.0f}ms): {r.on_answer}")
        else:
            print(render_failures_detail(rows))

        return 0
    finally:
        await service.close()


def main() -> None:
    args = parse_args()
    try:
        rc = asyncio.run(amain(args))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
