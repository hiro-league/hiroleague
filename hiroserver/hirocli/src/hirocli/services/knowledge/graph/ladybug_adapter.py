"""LadybugDB adapter for :class:`GraphStore`.

LadybugDB is the community Kuzu-lineage fork
(`pip install ladybug`, see `docs/knowledge-l3-content-routing-design.md` §6).
Native Windows wheels for cp310-314; embedded, single-file, no server, no JVM.

API mirrors Kuzu exactly:

>>> import ladybug as lb
>>> db = lb.Database("path/to/file.lbug")
>>> conn = lb.Connection(db)
>>> result = conn.execute("MATCH (n:Entity) RETURN n.name")

Single typed node table (``Entity``) + single typed rel table (``Rel``) discriminated
by a ``type`` / ``rel_type`` property. Simpler than per-type tables and matches the
"ontology is optional; fall back to generic Entity" decision (research §1.2).

Concurrency: one ``Connection`` per ``Database`` is fine for the prototype's
single-writer ingest path. If we ever need concurrent reads alongside writes,
``LadybugGraphStore`` should mint per-call connections from the shared ``Database``.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hiro_commons.log import Logger

from .store import GraphEdge, GraphNode, GraphStore, normalize_name

if TYPE_CHECKING:  # pragma: no cover — type-only
    import ladybug as lb  # noqa: F401

log = Logger.get("SVC.KNOWLEDGE.GRAPH")


# Cypher schema — kept here as constants so a schema bump is a code review event.
# Single node + single rel table is intentional (see module docstring).
#
# ``created_at`` is STRING (ISO-8601 UTC), not TIMESTAMP, by deliberate prototype
# choice: bi-temporal queries are non-goals (plan §6), and a string keeps the
# dataclass and round-trip uniform without datetime ↔ str conversions at every
# parameter binding. If/when temporal querying lands, this becomes a real
# TIMESTAMP and the dataclass + binder grow conversions.
_SCHEMA_ENTITY = """
CREATE NODE TABLE IF NOT EXISTS Entity(
    id STRING,
    name STRING,
    normalized_name STRING,
    type STRING,
    aliases STRING[],
    chunk_ids STRING[],
    document_ids STRING[],
    attrs_json STRING,
    created_at STRING,
    PRIMARY KEY (id)
)
""".strip()

_SCHEMA_REL = """
CREATE REL TABLE IF NOT EXISTS Rel(
    FROM Entity TO Entity,
    id STRING,
    source_id STRING,
    target_id STRING,
    rel_type STRING,
    chunk_ids STRING[],
    document_ids STRING[],
    attrs_json STRING,
    created_at STRING
)
""".strip()
# Note: ``source_id`` / ``target_id`` duplicate the implicit FROM/TO endpoints.
# We persist them explicitly because Ladybug's Cypher dialect lacks
# ``startNode(r)`` / ``endNode(r)`` projection helpers, so reading endpoint
# ids back through a path pattern would require dialect tricks or extra hops.
# The redundancy is harmless at our scale and keeps queries direct.


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _merge_unique(existing: list[str], incoming: tuple[str, ...]) -> list[str]:
    """Order-preserving union — provenance lists must MERGE (re-ingest must not
    erase prior chunk_id links). Cheap because lists stay short per entity."""
    seen: dict[str, None] = dict.fromkeys(existing)
    for item in incoming:
        if item and item not in seen:
            seen[item] = None
    return list(seen)


def _rows(result: Any) -> list[Any]:
    """Drain a Ladybug ``QueryResult`` to a list. The result object is iterable
    in Ladybug's API (matching Kuzu); we materialize for the small reads this
    prototype does."""
    return list(result)


def _row_to_node(row: Any) -> GraphNode:
    # Cypher: RETURN n.id, n.name, n.normalized_name, n.type, n.aliases,
    #                 n.chunk_ids, n.document_ids, n.attrs_json, n.created_at
    nid, name, norm, ntype, aliases, chunk_ids, doc_ids, attrs_json, created = (
        row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8],
    )
    return GraphNode(
        id=str(nid),
        name=str(name or ""),
        type=str(ntype or "Entity"),
        normalized_name=str(norm or ""),
        aliases=tuple(aliases or ()),
        chunk_ids=tuple(chunk_ids or ()),
        document_ids=tuple(doc_ids or ()),
        attrs=_parse_attrs(attrs_json),
        created_at=str(created or ""),
    )


def _row_to_edge(row: Any) -> GraphEdge:
    # Cypher: RETURN e.id, src.id, tgt.id, e.rel_type, e.chunk_ids,
    #                 e.document_ids, e.attrs_json, e.created_at
    eid, src, tgt, rtype, chunk_ids, doc_ids, attrs_json, created = (
        row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7],
    )
    return GraphEdge(
        id=str(eid),
        source_id=str(src),
        target_id=str(tgt),
        rel_type=str(rtype or ""),
        chunk_ids=tuple(chunk_ids or ()),
        document_ids=tuple(doc_ids or ()),
        attrs=_parse_attrs(attrs_json),
        created_at=str(created or ""),
    )


def _parse_attrs(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        log.warning("⚠️ graph — corrupt attrs_json on read · returning empty", raw=str(raw)[:120])
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _attrs_to_json(attrs: dict[str, Any]) -> str:
    return json.dumps(attrs, ensure_ascii=False, sort_keys=True) if attrs else ""


class LadybugGraphStore(GraphStore):
    """Embedded LadybugDB-backed :class:`GraphStore`.

    A single ``Database`` + ``Connection`` per instance. Construct via
    :meth:`open` (handles dir creation + schema init). Call :meth:`close` when
    done; the instance is also usable as a context manager.
    """

    def __init__(self, db: "lb.Database", conn: "lb.Connection", *, path: Path) -> None:
        self._db = db
        self._conn = conn
        self._path = path
        self._closed = False

    # ---- construction / teardown ----

    @classmethod
    def open(cls, path: Path) -> "LadybugGraphStore":
        """Open (or create) a Ladybug database at ``path`` and ensure the schema.

        The parent directory is created on demand — matches the workspace folder
        convention (``workspace/knowledge/graph/`` per ``constants.GRAPH_DIR``).
        Import is lazy so the rest of the package loads even when the dep is not
        yet installed (e.g. during the brief window after ``uv add`` but before
        ``uv sync``).
        """
        try:
            import ladybug as lb
        except ImportError as exc:  # pragma: no cover — install guidance
            raise RuntimeError(
                "LadybugDB is not installed. Run `uv add ladybug==0.17.0` in hiroserver/ "
                "(after stopping the dev server so hiro.exe can be relinked)."
            ) from exc

        path.parent.mkdir(parents=True, exist_ok=True)
        log.info("⬇️ graph — opening Ladybug database · path=%s", path)
        try:
            db = lb.Database(str(path))
            conn = lb.Connection(db)
        except Exception:
            log.exception("❌ graph — failed to open Ladybug database · path=%s", path)
            raise

        store = cls(db, conn, path=path)
        store._ensure_schema()
        return store

    def _ensure_schema(self) -> None:
        for ddl in (_SCHEMA_ENTITY, _SCHEMA_REL):
            try:
                self._conn.execute(ddl)
            except Exception:
                log.exception("❌ graph — schema init failed · ddl=%s", ddl.split("(", 1)[0])
                raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Ladybug (Kuzu lineage) releases on GC; nulling the refs is the documented
        # pattern. Wrap so partial-init objects do not crash the close path.
        try:
            del self._conn
            del self._db
        except Exception:
            log.warning("⚠️ graph — close encountered residual handle", exc_info=True)

    def __enter__(self) -> "LadybugGraphStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    # ---- writes ----

    def upsert_node(self, node: GraphNode) -> None:
        existing = self.get_node(node.id)
        merged_aliases = _merge_unique(list(existing.aliases) if existing else [], node.aliases)
        merged_chunks = _merge_unique(list(existing.chunk_ids) if existing else [], node.chunk_ids)
        merged_docs = _merge_unique(list(existing.document_ids) if existing else [], node.document_ids)
        attrs = {**(existing.attrs if existing else {}), **node.attrs}
        created_at = (existing.created_at if existing else node.created_at) or _now_iso()
        # Ladybug supports MERGE on a primary-key column; we use it for idempotency.
        # The ON CREATE / ON MATCH split keeps the timestamp + provenance correct.
        params = {
            "id": node.id,
            "name": node.name,
            "normalized_name": node.normalized_name or normalize_name(node.name),
            "type": node.type or "Entity",
            "aliases": merged_aliases,
            "chunk_ids": merged_chunks,
            "document_ids": merged_docs,
            "attrs_json": _attrs_to_json(attrs),
            "created_at": created_at,
        }
        cypher = """
        MERGE (n:Entity {id: $id})
        SET n.name = $name,
            n.normalized_name = $normalized_name,
            n.type = $type,
            n.aliases = $aliases,
            n.chunk_ids = $chunk_ids,
            n.document_ids = $document_ids,
            n.attrs_json = $attrs_json,
            n.created_at = $created_at
        """
        self._execute(cypher, params, op="upsert_node")

    def upsert_edge(self, edge: GraphEdge) -> None:
        # Resolve existing edge by id (the deterministic hash of src+rel+tgt) so we
        # can merge provenance. Edges between the same pair with different rel_type
        # are distinct edges by id, matching Graphiti's "same endpoints, different
        # predicate" model.
        existing_chunk_ids, existing_doc_ids, existing_attrs, existing_created = (
            self._get_edge_provenance(edge.id)
        )
        merged_chunks = _merge_unique(existing_chunk_ids, edge.chunk_ids)
        merged_docs = _merge_unique(existing_doc_ids, edge.document_ids)
        attrs = {**existing_attrs, **edge.attrs}
        created_at = existing_created or edge.created_at or _now_iso()
        params = {
            "src": edge.source_id,
            "tgt": edge.target_id,
            "id": edge.id,
            "rel_type": edge.rel_type,
            "chunk_ids": merged_chunks,
            "document_ids": merged_docs,
            "attrs_json": _attrs_to_json(attrs),
            "created_at": created_at,
        }
        cypher = """
        MATCH (a:Entity {id: $src}), (b:Entity {id: $tgt})
        MERGE (a)-[r:Rel {id: $id}]->(b)
        SET r.rel_type = $rel_type,
            r.source_id = $src,
            r.target_id = $tgt,
            r.chunk_ids = $chunk_ids,
            r.document_ids = $document_ids,
            r.attrs_json = $attrs_json,
            r.created_at = $created_at
        """
        self._execute(cypher, params, op="upsert_edge")

    # ---- reads ----

    def get_node(self, node_id: str) -> GraphNode | None:
        cypher = (
            "MATCH (n:Entity {id: $id}) "
            "RETURN n.id, n.name, n.normalized_name, n.type, n.aliases, "
            "n.chunk_ids, n.document_ids, n.attrs_json, n.created_at"
        )
        rows = _rows(self._execute(cypher, {"id": node_id}, op="get_node"))
        return _row_to_node(rows[0]) if rows else None

    def find_by_name_exact(
        self, normalized_name: str, *, type: str | None = None
    ) -> list[GraphNode]:
        # Match nodes whose canonical normalized_name equals the needle, OR whose
        # aliases[] contains the needle. Aliases are stored normalized at write
        # time (see GraphResolver._create / _link_provenance) so this is a direct
        # equality match — no per-row normalization on the read path.
        if type:
            cypher = (
                "MATCH (n:Entity) WHERE n.type = $type "
                "AND (n.normalized_name = $norm OR $norm IN n.aliases) "
                "RETURN n.id, n.name, n.normalized_name, n.type, n.aliases, "
                "n.chunk_ids, n.document_ids, n.attrs_json, n.created_at"
            )
            params = {"norm": normalized_name, "type": type}
        else:
            cypher = (
                "MATCH (n:Entity) WHERE n.normalized_name = $norm OR $norm IN n.aliases "
                "RETURN n.id, n.name, n.normalized_name, n.type, n.aliases, "
                "n.chunk_ids, n.document_ids, n.attrs_json, n.created_at"
            )
            params = {"norm": normalized_name}
        rows = _rows(self._execute(cypher, params, op="find_by_name_exact"))
        return [_row_to_node(row) for row in rows]

    def find_candidates_by_name(
        self, name: str, *, type: str | None = None, limit: int = 20
    ) -> list[GraphNode]:
        needle = normalize_name(name)
        if not needle:
            return []
        if type:
            cypher = (
                "MATCH (n:Entity) WHERE n.type = $type AND n.normalized_name CONTAINS $needle "
                "RETURN n.id, n.name, n.normalized_name, n.type, n.aliases, "
                "n.chunk_ids, n.document_ids, n.attrs_json, n.created_at LIMIT $limit"
            )
            params: dict[str, Any] = {"type": type, "needle": needle, "limit": int(limit)}
        else:
            cypher = (
                "MATCH (n:Entity) WHERE n.normalized_name CONTAINS $needle "
                "RETURN n.id, n.name, n.normalized_name, n.type, n.aliases, "
                "n.chunk_ids, n.document_ids, n.attrs_json, n.created_at LIMIT $limit"
            )
            params = {"needle": needle, "limit": int(limit)}
        rows = _rows(self._execute(cypher, params, op="find_candidates_by_name"))
        return [_row_to_node(row) for row in rows]

    def neighbors(
        self,
        node_id: str,
        *,
        k: int = 1,
        rel_types: list[str] | None = None,
    ) -> list[GraphNode]:
        # Variable-length is Cypher ``*1..k`` (Kuzu/Ladybug syntax). For k=1 this
        # is a direct neighbor; for k>1 a path expansion. Direction-agnostic
        # (-[]-) — graph semantics are undirected for the prototype.
        if k < 1:
            return []
        if rel_types:
            cypher = (
                f"MATCH (n:Entity {{id: $id}})-[r:Rel*1..{int(k)}]-(m:Entity) "
                "WHERE all(rel IN r WHERE rel.rel_type IN $rel_types) AND m.id <> $id "
                "RETURN DISTINCT m.id, m.name, m.normalized_name, m.type, m.aliases, "
                "m.chunk_ids, m.document_ids, m.attrs_json, m.created_at"
            )
            params: dict[str, Any] = {"id": node_id, "rel_types": list(rel_types)}
        else:
            cypher = (
                f"MATCH (n:Entity {{id: $id}})-[r:Rel*1..{int(k)}]-(m:Entity) "
                "WHERE m.id <> $id "
                "RETURN DISTINCT m.id, m.name, m.normalized_name, m.type, m.aliases, "
                "m.chunk_ids, m.document_ids, m.attrs_json, m.created_at"
            )
            params = {"id": node_id}
        rows = _rows(self._execute(cypher, params, op="neighbors"))
        return [_row_to_node(row) for row in rows]

    def edges(self, node_id: str, *, direction: str = "both") -> list[GraphEdge]:
        # Endpoints come from the persisted ``source_id`` / ``target_id`` columns
        # because Ladybug's Cypher lacks ``startNode(r)`` / ``endNode(r)``. The
        # MATCH pattern still filters by direction relative to ``node_id``.
        if direction == "out":
            pattern = "(n:Entity {id: $id})-[r:Rel]->(m:Entity)"
        elif direction == "in":
            pattern = "(n:Entity {id: $id})<-[r:Rel]-(m:Entity)"
        elif direction == "both":
            pattern = "(n:Entity {id: $id})-[r:Rel]-(m:Entity)"
        else:
            raise ValueError(f"direction must be 'out', 'in', or 'both', got {direction!r}")
        cypher = (
            f"MATCH {pattern} "
            "RETURN r.id, r.source_id, r.target_id, r.rel_type, "
            "r.chunk_ids, r.document_ids, r.attrs_json, r.created_at"
        )
        rows = _rows(self._execute(cypher, {"id": node_id}, op="edges"))
        return [_row_to_edge(row) for row in rows]

    def get_edge(self, edge_id: str) -> GraphEdge | None:
        cypher = (
            "MATCH ()-[r:Rel {id: $id}]->() "
            "RETURN r.id, r.source_id, r.target_id, r.rel_type, "
            "r.chunk_ids, r.document_ids, r.attrs_json, r.created_at"
        )
        rows = _rows(self._execute(cypher, {"id": edge_id}, op="get_edge"))
        return _row_to_edge(rows[0]) if rows else None

    def snapshot(
        self, *, node_limit: int | None = None, edge_limit: int | None = None
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        # Two unanchored scans (all nodes, all edges) — the only place this
        # adapter reads the whole graph. ``LIMIT`` is interpolated (not a param)
        # because Ladybug/Kuzu does not accept a parameter in the LIMIT clause;
        # the value is coerced to int so it is injection-safe.
        node_cypher = (
            "MATCH (n:Entity) "
            "RETURN n.id, n.name, n.normalized_name, n.type, n.aliases, "
            "n.chunk_ids, n.document_ids, n.attrs_json, n.created_at"
        )
        if node_limit is not None:
            node_cypher += f" LIMIT {int(node_limit)}"
        node_rows = _rows(self._execute(node_cypher, {}, op="snapshot_nodes"))
        nodes = [_row_to_node(row) for row in node_rows]

        edge_cypher = (
            "MATCH ()-[r:Rel]->() "
            "RETURN r.id, r.source_id, r.target_id, r.rel_type, "
            "r.chunk_ids, r.document_ids, r.attrs_json, r.created_at"
        )
        if edge_limit is not None:
            edge_cypher += f" LIMIT {int(edge_limit)}"
        edge_rows = _rows(self._execute(edge_cypher, {}, op="snapshot_edges"))
        edges = [_row_to_edge(row) for row in edge_rows]
        return nodes, edges

    # ---- helpers ----

    def _get_edge_provenance(
        self, edge_id: str
    ) -> tuple[list[str], list[str], dict[str, Any], str]:
        cypher = (
            "MATCH ()-[r:Rel {id: $id}]->() "
            "RETURN r.chunk_ids, r.document_ids, r.attrs_json, r.created_at"
        )
        rows = _rows(self._execute(cypher, {"id": edge_id}, op="_get_edge_provenance"))
        if not rows:
            return [], [], {}, ""
        chunks, docs, attrs_json, created = rows[0][0], rows[0][1], rows[0][2], rows[0][3]
        return list(chunks or []), list(docs or []), _parse_attrs(attrs_json), str(created or "")

    def _execute(self, cypher: str, params: dict[str, Any], *, op: str) -> Any:
        if self._closed:
            raise RuntimeError(f"graph — store is closed, cannot run {op}")
        try:
            return self._conn.execute(cypher, params)
        except Exception:
            # General-coding-rule: external-engine calls must log + raise. The op
            # tag identifies the call site so a ledger reader can trace failures
            # to a single line in this adapter.
            log.exception("❌ graph — Cypher failed · op=%s", op)
            raise


__all__ = ["LadybugGraphStore"]
