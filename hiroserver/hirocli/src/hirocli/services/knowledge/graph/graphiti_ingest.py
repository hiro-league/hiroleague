"""Graphiti ingest — map document chunks to Graphiti episodes (``add_episode``).

One chunk = one episode (decision G6): ``uuid = chunk_id`` (== the Qdrant
``point_id``), so the episode IS the citable chunk and ``EntityEdge.episodes``
gives native fact→chunk provenance. Episodes are fed **sequentially in
chronological order** so a later fact can supersede an earlier one (temporal
invalidation).

The **F7 write-gate** (mem0 #4573 bleed fix) sits in front of every
``add_episode``: only ``user_document`` content is ingested; retrieved/system/
assistant content is rejected before any model call — the graph cannot become a
stale echo of its own output, by construction.

This module is deliberately decoupled from :class:`GraphitiMemoryService`: it
takes the Graphiti client as an argument, so it is unit-testable with a fake
client (no Kuzu, no network). See docs/knowledge-graphiti-pivot-design.md §6.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graphiti_core.driver.driver import GraphProvider
from graphiti_core.graph_queries import get_fulltext_indices
from graphiti_core.nodes import EpisodeType, EpisodicNode
from hiro_commons.log import Logger
from pydantic import BaseModel

from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.runtime.agent_graph.tracing import traced_run

from ..constants import (
    KNOWLEDGE_GRAPH_EDGE_UPSERTED,
    KNOWLEDGE_GRAPH_INGEST_PROGRESS,
    KNOWLEDGE_GRAPH_NODE_UPSERTED,
)
from .graphiti_serialize import edge_to_dto, node_to_dto
from .group_scope import GroupPolicyError
from .ingest_ledger import (
    apply_episode_span_rollup,
    finalize_graph_ingest_run,
    knowledge_graph_ingest_ledger,
    ledger_episode,
)
from .ingest_trace import (
    IngestCapture,
    build_episode_trace,
    current_ingest_capture,
    write_ingest_trace_sidecar,
)

log = Logger.get("SVC.KNOWLEDGE.GRAPH.GRAPHITI.INGEST")



# Live-viz event sink: ``(event_type, payload) -> None``. None = no-op (CLI/tests).
GraphEventSink = Callable[[str, dict[str, Any]], None]

# (table, index_name) of every Kuzu FTS index — mirrors graphiti's CREATE DDL in
# ``graph_queries.get_fulltext_indices(KUZU)`` (kept in lockstep; the CREATE side reuses
# that helper, this list only supplies the DROP target names).
_KUZU_FTS_INDICES: tuple[tuple[str, str], ...] = (
    ("Episodic", "episode_content"),
    ("Entity", "node_name_and_summary"),
    ("Community", "community_name"),
    ("RelatesToNode_", "edge_name_and_fact"),
)


async def rebuild_fts_indices(driver: Any) -> None:
    """Drop + re-CREATE the Kuzu full-text indices so they cover all current rows.

    WHY: Kuzu's FTS index is a STATIC snapshot built at ``CREATE_FTS_INDEX`` time — it is
    NOT maintained as rows are inserted/updated/deleted. The indices are created once over
    (initially empty) tables at init, so every episode added afterward is invisible to
    ``QUERY_FTS_INDEX`` — the bm25 / keyword legs of search return nothing, and graphiti's
    own ingest dedup (which also queries the FTS index) is partly blind, causing duplicate
    facts. Re-creating re-indexes the WHOLE table, so this is called once per ingest batch
    (and once at init for pre-existing data) — never per episode.

    Only Kuzu needs this; neo4j/falkordb maintain their FTS indices automatically.
    """
    if getattr(driver, "provider", None) != GraphProvider.KUZU:
        return
    for table, name in _KUZU_FTS_INDICES:
        try:
            await driver.execute_query(f"CALL DROP_FTS_INDEX('{table}', '{name}');")
        except Exception as exc:
            # First-ever build: the index doesn't exist yet — that's fine, CREATE follows.
            # Kuzu phrases the missing-index DROP error as "Table X doesn't have an index
            # with name Y" (not "does not exist"), so match that shape too — otherwise the
            # very first rebuild on a fresh DB raises instead of falling through to CREATE.
            msg = str(exc).lower()
            if (
                "does not exist" in msg
                or "not found" in msg
                or "no index" in msg
                or "have an index" in msg
            ):
                continue
            log.exception("❌ graphiti — FTS drop failed · table=%s index=%s", table, name)
            raise
    for stmt in get_fulltext_indices(driver.provider):
        try:
            await driver.execute_query(stmt)
        except Exception:
            log.exception("❌ graphiti — FTS (re)create failed · stmt=%s", stmt[:64])
            raise
    log.info("✅ graphiti — Kuzu FTS indices rebuilt · count=%d", len(_KUZU_FTS_INDICES))

# F7 — source-role allow-list (supersedes the earlier ingest's gate). Allow-list,
# not deny-list: a future ingest path that forgets to tag its role is REJECTED by
# default. Add roles here explicitly as new ingest sources are wired up.
#   - "user_document": user-added knowledge documents (the L3 knowledge path).
#   - "conversation":  the USER half of a chat turn, ingested as long-term agent
#     memory (mem0→Graphiti replacement, Phase 1). Only the user message is allowed
#     in — never the assistant reply — so the memory graph can't become a stale echo
#     of its own output (#4573 anti-echo, design decision D2). The caller is what
#     enforces "user turn only"; the gate just admits the role.
ALLOWED_SOURCE_ROLES: frozenset[str] = frozenset({"user_document", "conversation"})


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class GraphitiEpisodeInput:
    """One chunk to ingest as a Graphiti episode.

    ``chunk_id`` becomes the episode ``uuid`` (== Qdrant ``point_id``) — the join
    key. ``reference_time`` drives temporal ordering/supersession; when ``None`` the
    ingest stamps "now". ``source`` is ``"text"`` (default) or ``"message"``.
    """

    chunk_id: str
    document_id: str
    text: str
    reference_time: dt.datetime | None = None
    document_title: str = ""
    source: str = "text"
    speaker: str = ""


@dataclass
class GraphitiIngestStats:
    """Per-job counters surfaced to the tool result / ledger."""

    episodes_received: int = 0
    episodes_processed: int = 0
    episodes_rejected: int = 0
    episodes_failed: int = 0
    entities_total: int = 0      # nodes touched across all episodes (created or merged)
    edges_total: int = 0         # facts touched across all episodes
    facts_invalidated: int = 0   # facts superseded (from the add_episode tracer span)
    tokens_input: int = 0        # LLM input tokens across episodes (ledgered path)
    tokens_output: int = 0       # LLM output tokens across episodes (ledgered path)
    rejected_roles: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "episodes_received": self.episodes_received,
            "episodes_processed": self.episodes_processed,
            "episodes_rejected": self.episodes_rejected,
            "episodes_failed": self.episodes_failed,
            "entities_total": self.entities_total,
            "edges_total": self.edges_total,
            "facts_invalidated": self.facts_invalidated,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "rejected_roles": list(self.rejected_roles),
        }


def _episode_name(ep: GraphitiEpisodeInput) -> str:
    label = ep.document_title or ep.document_id or "episode"
    return f"{label} · {ep.chunk_id[:8]}" if ep.chunk_id else label


def _episode_body(ep: GraphitiEpisodeInput, source: EpisodeType) -> str:
    if source == EpisodeType.message and ep.speaker:
        return f"{ep.speaker}: {ep.text}"
    return ep.text


async def _preseed_episode_node(
    driver: Any,
    ep: GraphitiEpisodeInput,
    *,
    body: str,
    source: EpisodeType,
    group_id: str | None,
    ref: dt.datetime,
    now: dt.datetime,
) -> None:
    """Create the Episodic node up-front with our ``uuid = chunk_id`` (== point_id).

    graphiti-core 0.29.1's ``add_episode(uuid=...)`` treats a supplied ``uuid`` as
    "UPDATE the existing episode" — it does ``EpisodicNode.get_by_uuid`` and raises
    ``NodeNotFoundError`` when the node doesn't exist yet. Our provenance bridge (G6)
    needs the *opposite*: CREATE the episode WITH that id so ``episode.uuid ==
    point_id`` (the Qdrant join key, no mapping table). So we persist the node first;
    ``add_episode`` then finds it via ``get_by_uuid`` and enriches it (extraction +
    edges) before re-saving. One extra write per chunk; keeps the design intact.
    """
    node = EpisodicNode(
        uuid=ep.chunk_id,
        name=_episode_name(ep),
        group_id=group_id or "",
        source=source,
        source_description=ep.document_id,
        content=body,
        valid_at=ref,
        created_at=now,
    )
    try:
        await node.save(driver)
    except Exception:
        # Real Kuzu write — fail loud + let the caller count/raise (general-coding-rule).
        log.exception(
            "❌ graphiti.ingest — episode pre-seed failed · chunk=%s doc=%s",
            ep.chunk_id,
            ep.document_id,
        )
        raise


def _safe_emit(
    event_sink: GraphEventSink | None, event_type: str, payload: dict[str, Any]
) -> None:
    # A viz event must never abort an ingest — swallow + log.
    if event_sink is None:
        return
    try:
        event_sink(event_type, payload)
    except Exception:
        log.warning("⚠️ graphiti.ingest — event emit failed · type=%s", event_type, exc_info=True)


def _result_names(result: Any) -> tuple[list[str], list[str]]:
    """Pull touched entity names + fact texts off ``AddEpisodeResults`` for the
    ledger ``persist`` row (so the run shows *what* the episode produced).

    Defensive: a missing attribute yields an empty list, never raises.
    """
    node_names = [str(getattr(n, "name", "") or "") for n in (getattr(result, "nodes", None) or [])]
    edge_facts = [
        str(getattr(e, "fact", "") or getattr(e, "name", "") or "")
        for e in (getattr(result, "edges", None) or [])
    ]
    return [n for n in node_names if n], [e for e in edge_facts if e]


def _emit_progress(
    event_sink: GraphEventSink | None,
    *,
    document_id: str,
    index: int,
    total: int,
    group_id: str | None = None,
) -> None:
    _safe_emit(
        event_sink,
        KNOWLEDGE_GRAPH_INGEST_PROGRESS,
        {
            "document_id": document_id,
            "chunk_index": index,
            "chunk_total": total,
            "group_id": group_id,
        },
    )


def _emit_graph_elements(
    event_sink: GraphEventSink | None,
    result: Any,
    *,
    document_id: str,
    group_id: str | None = None,
) -> None:
    """Emit a node/edge upserted event per element add_episode touched (live viz).

    ``is_new=True`` is best-effort: ``AddEpisodeResults`` doesn't distinguish
    created-vs-merged, so every touched element 'pops'; the reconcile-on-completed
    full export heals the final state. See docs/knowledge-graph-viz-design.md §4.1.

    ``group_id`` tags every event with its partition (knowledge default vs a
    ``mem_{user}_{character}`` conversation-memory group) so the admin Graph tab can route
    live deltas to the group it's currently viewing — the same SSE stream now carries both.
    """
    if event_sink is None:
        return
    # document_id is known here; pass it so live nodes/edges carry document provenance.
    # Node chunk_ids stay thin live (the node doesn't carry episodes) — the
    # reconcile-on-completed full export heals node chunk_ids/document_ids.
    doc_ids = [document_id] if document_id else []
    for node in getattr(result, "nodes", None) or []:
        _safe_emit(
            event_sink,
            KNOWLEDGE_GRAPH_NODE_UPSERTED,
            {"node": node_to_dto(node, document_ids=doc_ids), "is_new": True,
             "document_id": document_id, "group_id": group_id},
        )
    for edge in getattr(result, "edges", None) or []:
        _safe_emit(
            event_sink,
            KNOWLEDGE_GRAPH_EDGE_UPSERTED,
            {"edge": edge_to_dto(edge, document_ids=doc_ids), "is_new": True,
             "document_id": document_id, "group_id": group_id},
        )


async def ingest_episodes(
    graphiti: Any,
    episodes: Sequence[GraphitiEpisodeInput],
    *,
    source_role: str,
    group_id: str | None = None,
    entity_types: dict[str, type[BaseModel]] | None = None,
    edge_types: dict[str, type[BaseModel]] | None = None,
    edge_type_map: dict[tuple[str, str], list[str]] | None = None,
    custom_extraction_instructions: str | None = None,
    event_sink: GraphEventSink | None = None,
    ledger_sink: LedgerSink | None = None,
    observability: str = "ledger",
    write_lock: asyncio.Lock | None = None,
    workspace_path: Path | None = None,
    trace_name: str = "graph_ingest",
    rebuild_fts: bool = True,
) -> GraphitiIngestStats:
    """Ingest chunks as Graphiti episodes — sequential, chronological, write-gated.

    ``graphiti`` is anything exposing an async ``add_episode(...)`` (the real client
    or a test fake). Episodes are sorted by ``reference_time`` so temporal
    supersession is correct regardless of input order.

    ``ledger_sink`` (when given) records a ``graph_ingest`` run with a per-episode
    step and per-operation sub-step nodes (extract/resolve/dates/…), so ingestion
    is visible in Graph Runs (docs §6/§12). ``None`` = no ledger (tests/CLI).

    ``workspace_path`` is where the per-stage ingest-trace sidecar is written
    (``<workspace>/logs/ingest_trace/<run_id>.jsonl``) when ``observability == "trace"``
    AND a ledger sink is active (the trace dialog opens from a ledger row).
    ``None`` ⇒ no sidecar (tests/CLI), even at the trace tier.

    ``trace_name`` is the LangSmith span name for this ingest unit (default ``graph_ingest``).
    The memory-eval remember loop passes ``graph_ingest_{n}`` so each turn's tree is numbered.
    """
    stats = GraphitiIngestStats(episodes_received=len(episodes))
    # Run row groups all episodes from this call (== one document for the per-doc
    # tool path; the whole series for an eval corpus sharing one document_id).
    doc_id = episodes[0].document_id if episodes else ""
    doc_title = episodes[0].document_title if episodes else ""

    async with knowledge_graph_ingest_ledger(
        sink=ledger_sink, document_id=doc_id
    ) as run:
        try:
            # F7 write-gate — one log + bail, before any model call.
            if source_role not in ALLOWED_SOURCE_ROLES:
                stats.episodes_rejected = len(episodes)
                if source_role:
                    stats.rejected_roles.append(source_role)
                log.warning(
                    "❌ graphiti.ingest — REJECTED %d episode(s) · role=%s not in allow-list %s",
                    len(episodes),
                    source_role,
                    sorted(ALLOWED_SOURCE_ROLES),
                )
                if run.accumulator is not None and not run.nested:
                    finalize_graph_ingest_run(
                        run.accumulator,
                        document_id=doc_id,
                        document_title=doc_title,
                        source_role=source_role,
                        episode_count=len(episodes),
                        stats=stats,
                        status="completed",  # finalize maps rejected>0 → "rejected"
                    )
                return stats

            if not episodes:
                return stats

            # Anti-catch-all guard (defense-in-depth, docs/graph-group-policy-design.md §6):
            # an actual write MUST name a non-empty partition. The empty group_id is
            # graphiti's catch-all on Kuzu — exactly what let knowledge search leak
            # conversation memory — so never write into it. Callers mint a namespaced group
            # (kb_/mem_/eval_) via group_scope; the service boundary additionally validates the
            # namespace. Here we only forbid the empty group so this primitive stays generic.
            # Placed AFTER the role gate + empty-episode check so legit no-ops need no group.
            if not group_id:
                raise GroupPolicyError(
                    "ingest_episodes requires a non-empty group_id (no catch-all writes)"
                )

            # Stamp + sort by reference_time so a later fact supersedes an earlier one.
            prepared = sorted(
                ((ep, ep.reference_time or _now()) for ep in episodes),
                key=lambda pair: pair[1],
            )
            total = len(prepared)

            # Full per-stage ingest trace (eval / Graph-Runs inspection) — the ``trace`` tier.
            # Engaged only when a ledger run + workspace exist to anchor/persist the sidecar
            # (the dialog opens from a ledger row, so a trace without one is useless).
            ingest_trace_on = (
                observability == "trace"
                and run.sink is not None
                and workspace_path is not None
            )
            log.info(
                "🔎 graph_ingest — ingest trace %s · observability=%s",
                "ON" if ingest_trace_on else "off",
                observability,
            )
            if ingest_trace_on:
                # Install the transparent observer for graphiti's NON-LLM entity dedup
                # (exact/fuzzy auto-merges that skip the LLM). Idempotent + best-effort: a
                # compat drift just skips dedup rows (LLM stages still captured), never
                # breaks this write path.
                from .graphiti_dedup_trace import install_dedup_trace

                install_dedup_trace()

            # Real Graphiti exposes `.driver`; the unit-test fake does not → pre-seed only
            # on the real path (production always has a driver). Lets the fake-client tests
            # stay Kuzu-free while the live path creates episodes with our point_id.
            driver = getattr(graphiti, "driver", None)
            # Serialize writers to one episode at a time (Kuzu single-writer + graphiti
            # sequential dedup); held per-episode and released between (docs §4.2). The
            # fake-client unit tests pass write_lock=None → a no-op guard.
            write_guard = write_lock if write_lock is not None else contextlib.nullcontext()

            # Group every episode of this ingest under ONE LangSmith trace so Graphiti's
            # internal LLM calls (extract entities / dedupe / date facts …) read as one tree
            # instead of scattering as a separate root per call (the reason ingestion looked
            # scattered in LangSmith). Force the deterministic ledger run id only on a
            # STANDALONE ingest; when nested under an eval/chat run we just attach to its
            # active span via contextvars. No-op when LangSmith tracing is off.
            ingest_run_id = run.run_id if (run.run_id and not run.nested) else None
            with traced_run(
                trace_name,
                ledger_run_id=ingest_run_id,
                tags=[f"role:{source_role}", f"group:{group_id}"],
                metadata={"document_id": doc_id, "episode_count": total},
            ):
                for index, (ep, ref) in enumerate(prepared):
                    # Compute body before the ledger context so the episode step can show the
                    # ingested text in its input preview (#1).
                    source = EpisodeType.message if ep.source == "message" else EpisodeType.text
                    body = _episode_body(ep, source)
                    async with ledger_episode(
                        run,
                        episode_index=index + 1,
                        total=total,
                        chunk_id=ep.chunk_id,
                        document_id=ep.document_id,
                        title=ep.document_title,
                        reference_time=ref,
                        text=body,
                    ) as episode:
                        # Engage the opt-in per-stage ingest trace for THIS episode: the LLM
                        # adapter mirrors every stage's full in/out into this capture while
                        # add_episode runs (gathered sub-tasks inherit the context). No-op when
                        # tracing is off, so the production path is untouched.
                        capture = IngestCapture() if ingest_trace_on else None
                        cap_token = (
                            current_ingest_capture.set(capture) if capture is not None else None
                        )
                        # One child span per episode: Graphiti's per-episode LLM calls nest
                        # under it, mirroring the ledger's per-episode step. Scoped to the
                        # add_episode unit only (post-processing below is cheap bookkeeping).
                        with traced_run(
                            "add_episode",
                            tags=[f"chunk:{ep.chunk_id[:8]}"] if ep.chunk_id else None,
                            metadata={
                                "document_id": ep.document_id,
                                "index": index + 1,
                                "total": total,
                            },
                            inputs={"name": _episode_name(ep)},
                        ):
                            try:
                                # One writer at a time: preseed + add_episode are this
                                # episode's write unit. The lock spans the WHOLE add_episode
                                # (not just the kuzu write) because graphiti's dedup reads prior
                                # graph state to merge entities — concurrent episodes would
                                # dedup stale (§4.2).
                                async with write_guard:
                                    # Multi-group fix (memory Phase 1): graphiti-core's
                                    # add_episode compares ``group_id != driver._database`` and,
                                    # on a mismatch, takes a Neo4j-only "clone to a per-group
                                    # database" branch that breaks on Kuzu. Conversation memory
                                    # writes MANY groups (one per user×character) to the SAME
                                    # shared Kuzu driver, so we re-point ``_database`` to THIS
                                    # episode's group inside the single-writer lock (no race)
                                    # before add_episode. Knowledge (one fixed group) just
                                    # re-sets the value it was seeded with → a no-op there.
                                    if driver is not None and group_id:
                                        driver._database = group_id
                                    if driver is not None and ep.chunk_id:
                                        await _preseed_episode_node(
                                            driver,
                                            ep,
                                            body=body,
                                            source=source,
                                            group_id=group_id,
                                            ref=ref,
                                            now=_now(),
                                        )
                                    result = await graphiti.add_episode(
                                        name=_episode_name(ep),
                                        episode_body=body,
                                        source_description=ep.document_id,
                                        reference_time=ref,
                                        source=source,
                                        group_id=group_id,
                                        uuid=ep.chunk_id or None,
                                        entity_types=entity_types,
                                        edge_types=edge_types,
                                        edge_type_map=edge_type_map,
                                        # graphiti's extraction-prompt slot (node + edge); None ⇒ "".
                                        custom_extraction_instructions=custom_extraction_instructions,
                                    )
                            except Exception:
                                # External model + DB call — log + re-raise (general-coding-rule).
                                stats.episodes_failed += 1
                                if cap_token is not None:
                                    current_ingest_capture.reset(cap_token)
                                    cap_token = None
                                log.exception(
                                    "❌ graphiti.ingest — add_episode failed · chunk=%s doc=%s",
                                    ep.chunk_id,
                                    ep.document_id,
                                )
                                raise

                        # add_episode done — drop the capture engagement (post-processing below
                        # makes no model calls). The captured stages live on ``capture``.
                        if cap_token is not None:
                            current_ingest_capture.reset(cap_token)
                            cap_token = None

                        stats.episodes_processed += 1
                        node_names, edge_facts = _result_names(result)
                        stats.entities_total += len(getattr(result, "nodes", None) or [])
                        stats.edges_total += len(getattr(result, "edges", None) or [])
                        if episode is not None:
                            episode.set_persist(node_names=node_names, edge_facts=edge_facts)
                            # Fold this episode's supersession + token totals into the run
                            # stats (§12). invalidated_count comes from the add_episode
                            # tracer span (already buffered now that add_episode returned);
                            # tokens come from the per-call usage sink. Ledgered path only —
                            # without a sink there's no collector and these stay 0.
                            apply_episode_span_rollup(episode)
                            stats.facts_invalidated += episode.invalidated_count
                            stats.tokens_input += episode.total_input_tokens
                            stats.tokens_output += episode.total_output_tokens
                        # Persist the full per-stage trace sidecar (when capture engaged) keyed
                        # by this run + episode step, so the ingest-trace dialog can link it to
                        # this episode row. Best-effort: a trace IO/render hiccup never aborts.
                        if (
                            capture is not None
                            and episode is not None
                            and workspace_path is not None
                            and run.run_id
                        ):
                            try:
                                trace = build_episode_trace(
                                    capture=capture,
                                    chunk_id=ep.chunk_id,
                                    episode_index=index + 1,
                                    total=total,
                                    name=_episode_name(ep),
                                    text=body,
                                    group_id=group_id or "",
                                    reference_time=(
                                        ref.isoformat() if hasattr(ref, "isoformat") else str(ref)
                                    ),
                                    result=result,
                                    invalidated_count=episode.invalidated_count,
                                )
                                write_ingest_trace_sidecar(
                                    workspace_path,
                                    run_id=run.run_id,
                                    step_index=episode.step_index,
                                    trace=trace,
                                )
                            except Exception:
                                log.warning(
                                    "⚠️ graphiti.ingest — ingest trace assemble/write failed · "
                                    "chunk=%s",
                                    ep.chunk_id,
                                    exc_info=True,
                                )
                        _emit_graph_elements(
                            event_sink, result, document_id=ep.document_id, group_id=group_id
                        )
                        _emit_progress(
                            event_sink,
                            document_id=ep.document_id,
                            index=index + 1,
                            total=total,
                            group_id=group_id,
                        )

            # Kuzu FTS is a static snapshot (not maintained on insert) — refresh it now that
            # this batch's edges/nodes/episodes are written, so keyword (bm25) search legs and
            # graphiti's dedup can see them. Done once per batch (not per episode) under the
            # single-writer lock, since DROP/CREATE_FTS_INDEX are writes.
            # ``rebuild_fts=False`` defers it: a caller looping many SINGLE-episode ingests (the
            # memory remember batch) would otherwise force a Kuzu CHECKPOINT per episode — each
            # one stalls until every concurrent READ leaves (the Graph-tab live export), which is
            # exactly the "Timeout waiting for active transactions before checkpointing" freeze.
            # Such callers pass False here and rebuild ONCE at the end of their batch instead.
            if rebuild_fts and driver is not None and stats.episodes_processed > 0:
                async with write_guard:
                    await rebuild_fts_indices(driver)

            log.info(
                "✅ graphiti.ingest — done · episodes=%d/%d entities=%d edges=%d",
                stats.episodes_processed,
                stats.episodes_received,
                stats.entities_total,
                stats.edges_total,
            )
        except Exception as exc:
            if run.accumulator is not None and not run.nested:
                finalize_graph_ingest_run(
                    run.accumulator,
                    document_id=doc_id,
                    document_title=doc_title,
                    source_role=source_role,
                    episode_count=stats.episodes_processed,
                    stats=stats,
                    status="failed",
                    error_code=type(exc).__name__,
                )
            raise
        else:
            if run.accumulator is not None and not run.nested:
                finalize_graph_ingest_run(
                    run.accumulator,
                    document_id=doc_id,
                    document_title=doc_title,
                    source_role=source_role,
                    episode_count=stats.episodes_received,
                    stats=stats,
                    status="completed",
                )
        return stats


__all__ = [
    "ALLOWED_SOURCE_ROLES",
    "GraphEventSink",
    "GraphitiEpisodeInput",
    "GraphitiIngestStats",
    "ingest_episodes",
]
