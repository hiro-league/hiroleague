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

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from graphiti_core.nodes import EpisodeType, EpisodicNode
from hiro_commons.log import Logger
from pydantic import BaseModel

from hirocli.runtime.agent_graph.ledger import LedgerSink

from ..constants import (
    KNOWLEDGE_GRAPH_EDGE_UPSERTED,
    KNOWLEDGE_GRAPH_INGEST_PROGRESS,
    KNOWLEDGE_GRAPH_NODE_UPSERTED,
)
from .graphiti_serialize import edge_to_dto, node_to_dto
from .ingest_ledger import (
    apply_episode_span_rollup,
    finalize_graph_ingest_run,
    knowledge_graph_ingest_ledger,
    ledger_episode,
)

log = Logger.get("SVC.KNOWLEDGE.GRAPH.GRAPHITI.INGEST")

# Live-viz event sink: ``(event_type, payload) -> None``. None = no-op (CLI/tests).
GraphEventSink = Callable[[str, dict[str, Any]], None]

# F7 — source-role allow-list (supersedes the Ladybug ingest's gate). Allow-list,
# not deny-list: a future ingest path that forgets to tag its role is REJECTED by
# default. Add roles here explicitly as new ingest sources are wired up.
ALLOWED_SOURCE_ROLES: frozenset[str] = frozenset({"user_document"})


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
    event_sink: GraphEventSink | None, *, document_id: str, index: int, total: int
) -> None:
    _safe_emit(
        event_sink,
        KNOWLEDGE_GRAPH_INGEST_PROGRESS,
        {"document_id": document_id, "chunk_index": index, "chunk_total": total},
    )


def _emit_graph_elements(
    event_sink: GraphEventSink | None, result: Any, *, document_id: str
) -> None:
    """Emit a node/edge upserted event per element add_episode touched (live viz).

    ``is_new=True`` is best-effort: ``AddEpisodeResults`` doesn't distinguish
    created-vs-merged, so every touched element 'pops'; the reconcile-on-completed
    full export heals the final state. See docs/knowledge-graph-viz-design.md §4.1.
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
             "document_id": document_id},
        )
    for edge in getattr(result, "edges", None) or []:
        _safe_emit(
            event_sink,
            KNOWLEDGE_GRAPH_EDGE_UPSERTED,
            {"edge": edge_to_dto(edge, document_ids=doc_ids), "is_new": True,
             "document_id": document_id},
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
    event_sink: GraphEventSink | None = None,
    ledger_sink: LedgerSink | None = None,
    ledger_detail: str = "rich",
) -> GraphitiIngestStats:
    """Ingest chunks as Graphiti episodes — sequential, chronological, write-gated.

    ``graphiti`` is anything exposing an async ``add_episode(...)`` (the real client
    or a test fake). Episodes are sorted by ``reference_time`` so temporal
    supersession is correct regardless of input order.

    ``ledger_sink`` (when given) records a ``graph_ingest`` run with a per-episode
    step and per-operation sub-step nodes (extract/resolve/dates/…), so ingestion
    is visible in Graph Runs (docs §6/§12). ``None`` = no ledger (tests/CLI).
    """
    stats = GraphitiIngestStats(episodes_received=len(episodes))
    # Run row groups all episodes from this call (== one document for the per-doc
    # tool path; the whole series for an eval corpus sharing one document_id).
    doc_id = episodes[0].document_id if episodes else ""
    doc_title = episodes[0].document_title if episodes else ""

    async with knowledge_graph_ingest_ledger(
        sink=ledger_sink, document_id=doc_id, ledger_detail=ledger_detail
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

            # Stamp + sort by reference_time so a later fact supersedes an earlier one.
            prepared = sorted(
                ((ep, ep.reference_time or _now()) for ep in episodes),
                key=lambda pair: pair[1],
            )
            total = len(prepared)

            # Real Graphiti exposes `.driver`; the unit-test fake does not → pre-seed only
            # on the real path (production always has a driver). Lets the fake-client tests
            # stay Kuzu-free while the live path creates episodes with our point_id.
            driver = getattr(graphiti, "driver", None)

            for index, (ep, ref) in enumerate(prepared):
                async with ledger_episode(
                    run,
                    episode_index=index + 1,
                    total=total,
                    chunk_id=ep.chunk_id,
                    document_id=ep.document_id,
                    title=ep.document_title,
                    reference_time=ref,
                ) as episode:
                    source = EpisodeType.message if ep.source == "message" else EpisodeType.text
                    body = _episode_body(ep, source)
                    try:
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
                        )
                    except Exception:
                        # External model + DB call — log + re-raise (general-coding-rule).
                        stats.episodes_failed += 1
                        log.exception(
                            "❌ graphiti.ingest — add_episode failed · chunk=%s doc=%s",
                            ep.chunk_id,
                            ep.document_id,
                        )
                        raise

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
                    _emit_graph_elements(event_sink, result, document_id=ep.document_id)
                    _emit_progress(
                        event_sink, document_id=ep.document_id, index=index + 1, total=total
                    )

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
