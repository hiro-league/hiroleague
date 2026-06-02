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

from graphiti_core.nodes import EpisodeType
from hiro_commons.log import Logger
from pydantic import BaseModel

from ..constants import (
    KNOWLEDGE_GRAPH_EDGE_UPSERTED,
    KNOWLEDGE_GRAPH_INGEST_PROGRESS,
    KNOWLEDGE_GRAPH_NODE_UPSERTED,
)
from .graphiti_serialize import edge_to_dto, node_to_dto

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
    rejected_roles: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "episodes_received": self.episodes_received,
            "episodes_processed": self.episodes_processed,
            "episodes_rejected": self.episodes_rejected,
            "episodes_failed": self.episodes_failed,
            "entities_total": self.entities_total,
            "edges_total": self.edges_total,
            "rejected_roles": list(self.rejected_roles),
        }


def _episode_name(ep: GraphitiEpisodeInput) -> str:
    label = ep.document_title or ep.document_id or "episode"
    return f"{label} · {ep.chunk_id[:8]}" if ep.chunk_id else label


def _episode_body(ep: GraphitiEpisodeInput, source: EpisodeType) -> str:
    if source == EpisodeType.message and ep.speaker:
        return f"{ep.speaker}: {ep.text}"
    return ep.text


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
    for node in getattr(result, "nodes", None) or []:
        _safe_emit(
            event_sink,
            KNOWLEDGE_GRAPH_NODE_UPSERTED,
            {"node": node_to_dto(node), "is_new": True, "document_id": document_id},
        )
    for edge in getattr(result, "edges", None) or []:
        _safe_emit(
            event_sink,
            KNOWLEDGE_GRAPH_EDGE_UPSERTED,
            {"edge": edge_to_dto(edge), "is_new": True, "document_id": document_id},
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
) -> GraphitiIngestStats:
    """Ingest chunks as Graphiti episodes — sequential, chronological, write-gated.

    ``graphiti`` is anything exposing an async ``add_episode(...)`` (the real client
    or a test fake). Episodes are sorted by ``reference_time`` so temporal
    supersession is correct regardless of input order.
    """
    stats = GraphitiIngestStats(episodes_received=len(episodes))

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
        return stats

    if not episodes:
        return stats

    # Stamp + sort by reference_time so a later fact supersedes an earlier one.
    prepared = sorted(
        ((ep, ep.reference_time or _now()) for ep in episodes), key=lambda pair: pair[1]
    )
    total = len(prepared)

    for index, (ep, ref) in enumerate(prepared):
        source = EpisodeType.message if ep.source == "message" else EpisodeType.text
        try:
            result = await graphiti.add_episode(
                name=_episode_name(ep),
                episode_body=_episode_body(ep, source),
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
        stats.entities_total += len(getattr(result, "nodes", None) or [])
        stats.edges_total += len(getattr(result, "edges", None) or [])
        _emit_graph_elements(event_sink, result, document_id=ep.document_id)
        _emit_progress(event_sink, document_id=ep.document_id, index=index + 1, total=total)

    log.info(
        "✅ graphiti.ingest — done · episodes=%d/%d entities=%d edges=%d",
        stats.episodes_processed,
        stats.episodes_received,
        stats.entities_total,
        stats.edges_total,
    )
    return stats


__all__ = [
    "ALLOWED_SOURCE_ROLES",
    "GraphEventSink",
    "GraphitiEpisodeInput",
    "GraphitiIngestStats",
    "ingest_episodes",
]
