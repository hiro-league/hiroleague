"""Building a knowledge graph from a collection's documents: one Graphiti episode per chunk (the episode's uuid is the
chunk's Qdrant point id, so the graph leg finds its passages again), and removing a document's episodes.

The owner builds the ``GraphitiMemoryService`` (its models, embedder, Kuzu file and group: the core's ``kb_main``,
EvalHiro's ``eval_kb_<corpus>``), hands it in and closes it; these never build or close one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from hiro_commons.log import Logger

from hiro_memory.graph import GraphitiEpisodeInput

if TYPE_CHECKING:
    from hiro_memory.graph import GraphitiMemoryService
    from hiro_memory.graph.graphiti_ingest import GraphEventSink
    from hiro_memory.knowledge.index import KnowledgeIndex
    from hiro_memory.ledger.sink import LedgerSink

log = Logger.get("SVC.KNOWLEDGE.GRAPH.TOOL")

# Chunks per document we pull in one round-trip from Qdrant. Documents larger
# than this are paged via scroll_offset. 200 covers a typical .md note.
CHUNK_PAGE_SIZE = 200


async def gather_document_episodes(
    index: "KnowledgeIndex", document_id: str
) -> tuple[list[GraphitiEpisodeInput], str | None]:
    """Walk all pages of a document's chunks → episodes. Returns (episodes, title)."""
    episodes: list[GraphitiEpisodeInput] = []
    title: str | None = None
    offset: str | None = None
    while True:
        detail = await index.get_document(
            document_id, chunk_limit=CHUNK_PAGE_SIZE, chunk_offset=offset
        )
        if detail.document is None:
            raise KeyError(f"Unknown knowledge document: {document_id}")
        title = detail.document.title or title
        for raw in detail.chunks:
            text = str(raw.get("text") or "").strip()
            point_id = str(raw.get("point_id") or "")
            if not text or not point_id:
                continue
            episodes.append(
                GraphitiEpisodeInput(
                    chunk_id=point_id,
                    document_id=document_id,
                    text=text,
                    document_title=title or "",
                )
            )
        offset = detail.chunk_next_offset
        if not offset:
            break
    return episodes, title


def empty_graph_totals() -> dict[str, int]:
    return {
        "episodes_processed": 0,
        "episodes_rejected": 0,
        "episodes_failed": 0,
        "entities_total": 0,
        "edges_total": 0,
    }


def _fold_into_totals(totals: dict[str, int], stats: dict[str, Any]) -> None:
    for key in totals:
        value = stats.get(key)
        if isinstance(value, (int, float)):
            totals[key] += int(value)


async def build_document_graph(
    service: "GraphitiMemoryService",
    index: "KnowledgeIndex",
    document_ids: list[str],
    *,
    source_role: str,
    ledger_sink: "LedgerSink | None" = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    event_sink: "GraphEventSink | None" = None,
) -> dict[str, Any]:
    """Ingest each document's chunks as episodes into ``service``'s group: {document_count, documents, totals}.

    Initializes the service once, then iterates documents — so a batch pays one setup
    cost, not N. Per-document failures are **isolated**: a bad doc is marked
    ``ok=False`` with its error and the batch continues.

    ``on_progress`` fires after each document. ``event_sink`` makes ingest emit live progress events.
    ``ledger_sink`` gives each document's build its own ledger run (drillable in Graph Runs)."""
    per_doc: list[dict[str, Any]] = []
    totals = empty_graph_totals()
    if not document_ids:
        return {"document_count": 0, "documents": per_doc, "totals": totals}
    await service.initialize()
    for index_no, document_id in enumerate(document_ids):
        entry: dict[str, Any] = {
            "index": index_no,
            "total": len(document_ids),
            "document_id": document_id,
            "document_title": "",
            "ok": False,
            "stats": None,
            "error": "",
        }
        try:
            episodes, title = await gather_document_episodes(index, document_id)
            entry["document_title"] = title or ""
            log.info(
                "⬇️ graphiti.ingest — %d episode(s) from document · doc_id=%s title=%r",
                len(episodes),
                document_id,
                title or "",
            )
            stats = await service.ingest_chunks(
                episodes,
                source_role=source_role,
                event_sink=event_sink,
                ledger_sink=ledger_sink,
                # Defer the per-document Kuzu FTS rebuild: N docs would otherwise force N
                # checkpoints, each able to stall against a concurrent graph read (the
                # memory-eval freeze, same class). ONE rebuild after the loop instead.
                rebuild_fts=False,
            )
            stats_dict = stats.as_dict()
            entry["ok"] = True
            entry["stats"] = stats_dict
            _fold_into_totals(totals, stats_dict)
        except Exception as exc:
            # Per-doc failure isolation. Log + record + continue.
            log.warning(
                "⚠️ graphiti.ingest — document failed · doc_id=%s · %s",
                document_id,
                str(exc)[:200],
                exc_info=True,
            )
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        per_doc.append(entry)
        if on_progress is not None:
            try:
                on_progress(dict(entry))
            except Exception:
                log.exception("⚠️ graphiti.ingest — on_progress callback failed")
    # One FTS rebuild for the whole batch (per-doc rebuilds deferred above). NON-FATAL:
    # the docs' episodes are already committed — a failed rebuild only leaves the keyword
    # index stale until the next graph open (initialize() rebuilds it). Aborting here would
    # mark a fully-built (paid-for) batch failed.
    if any(e["ok"] for e in per_doc):
        try:
            await service.rebuild_search_index()
        except Exception:
            log.warning(
                "⚠️ graphiti.ingest — batch FTS rebuild failed; episodes are committed, "
                "keyword index refreshes on next graph open",
                exc_info=True,
            )
    return {
        "document_count": len(document_ids),
        "documents": per_doc,
        "totals": totals,
    }


async def remove_document_episodes(service: "GraphitiMemoryService", document_id: str) -> int:
    """Delete one document's episodes (+ the entities/facts they exclusively own) from ``service``'s group, keeping
    its Qdrant chunks. Idempotent: a missing/blank document removes 0."""
    did = (document_id or "").strip()
    if not did:
        return 0
    await service.initialize()
    removed = await service.remove_episodes_by_document(did)
    log.info("🧹 knowledge graph — document removed · doc_id=%s episodes=%d", did, removed)
    return removed


__all__ = [
    "CHUNK_PAGE_SIZE",
    "build_document_graph",
    "empty_graph_totals",
    "gather_document_episodes",
    "remove_document_episodes",
]
