"""Readable "graph has been indexed" marker — the lock signal for the graph embedder.

The Kuzu graph DB is exclusively locked while the server runs, so it can't be opened externally to
count nodes for the embedder lock. Instead the ingest path writes a tiny sentinel file next to the
DB on the first successful episode write; the graph-embedder lock (UI badge + pre-save write-guard)
reads it. Conservative on purpose: group-scoped deletes do NOT clear it, because changing a
dimension-bound embedder after ANY ingest could orphan stored vectors — so it stays set until the
graph is fully reset (``clear_graph_indexed``).
"""

from __future__ import annotations

from pathlib import Path

from hiro_commons.log import Logger

from hirocli.services.knowledge.constants import GRAPH_DIR, KNOWLEDGE_DIR

log = Logger.get("SVC.KNOWLEDGE.GRAPH")

_MARKER_NAME = ".graph_indexed"


def graph_index_marker_path(workspace_path: Path) -> Path:
    return Path(workspace_path) / KNOWLEDGE_DIR / GRAPH_DIR / _MARKER_NAME


def is_graph_indexed(workspace_path: Path) -> bool:
    """True once the graph has had at least one successful ingest (and not been fully reset)."""
    try:
        return graph_index_marker_path(workspace_path).exists()
    except OSError:
        return False


def mark_graph_indexed(workspace_path: Path) -> None:
    """Record that the graph now holds data (idempotent). Best-effort — never breaks ingest."""
    try:
        path = graph_index_marker_path(workspace_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("1", encoding="utf-8")
            log.info("🔒 Graph embedder locked — HiroServer · first graph ingest recorded")
    except OSError:
        log.warning("⚠️ Could not write graph-indexed marker — HiroServer", exc_info=True)


def clear_graph_indexed(workspace_path: Path) -> None:
    """Clear the marker on a full graph reset, re-allowing an embedder change. Best-effort."""
    try:
        graph_index_marker_path(workspace_path).unlink(missing_ok=True)
    except OSError:
        log.warning("⚠️ Could not clear graph-indexed marker — HiroServer", exc_info=True)


async def graph_has_data(workspace_path: Path) -> bool:
    """Authoritative live check: does the graph currently hold any data?

    The marker (set on ingest) misses data that predates it, so this is the source of truth. It
    reads the live graph **in-process** via the shared Kuzu driver — safe while the server runs
    (only EXTERNAL opens collide). Short-circuits when the DB file is absent. Any existing group id
    means nodes/episodes exist. Fails SAFE (returns True) if the read errors, so we never unlock a
    populated graph by accident."""
    from hirocli.services.knowledge.graph.graphiti_service import (
        graphiti_db_path,
        read_graph_group_ids,
    )

    db = graphiti_db_path(workspace_path)
    if not db.exists():
        return False
    try:
        group_ids, _ = await read_graph_group_ids(db)
    except Exception:
        log.warning(
            "⚠️ graph-has-data check failed — assuming indexed (safe) — HiroServer", exc_info=True
        )
        return True
    return bool(group_ids)


async def sync_graph_indexed_marker(workspace_path: Path) -> bool:
    """Reconcile the marker with live graph data; return the resulting locked state.

    Backfills workspaces whose graph was populated before the marker existed, and clears it after a
    full wipe. Async (live read) — call it from the admin GET path so the sync ``is_graph_indexed``
    (read by the sync write-guards) reflects reality."""
    has = await graph_has_data(workspace_path)
    if has:
        mark_graph_indexed(workspace_path)
    else:
        clear_graph_indexed(workspace_path)
    return has
