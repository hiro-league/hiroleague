"""Bounded-memory BFS hop-expansion legs for the re-hosted graphiti fact search.

Why this module exists: graphiti-core 0.29.1's Kuzu fallbacks for
``search_utils.edge_bfs_search`` / ``node_bfs_search`` enumerate **all paths** up
to the hop bound (``MATCH path = (origin)-[:RELATES_TO*1..d]->…`` plus
``UNWIND nodes(path)``, with a trailing ``RETURN DISTINCT`` that prevents any
LIMIT early-exit). Path counts grow ~degree^depth through hub entities, so on a
hub-heavy graph (e.g. the LoCoMo eval corpus, where the two speakers carry ~200
facts each) ``k_hop=3`` materializes tens of millions of path rows and aborts
with *"Buffer manager exception: Unable to allocate memory!"*. Captured query +
replay evidence: docs/kuzu-bfs-path-explosion-design.md.

The result the hop expansion actually needs is the **reachable set** (facts /
entities within k hops), which Kuzu computes in linear memory with its
``* SHORTEST`` recursive-relationship semantics: a node lies on *some* path of
length <= d from an origin iff its *shortest* path from that origin is <= d, so
the destination set is identical while the engine visits each node once instead
of once per path. Set-equality between both shapes is enforced by the parity
tests in ``test_graphiti_bfs.py`` and was additionally verified against the real
eval graph (482/482 identical fact uuids at depth 3; 82 ms at depth 5 where the
vendored shape exhausted a 4 GB buffer pool).

Kuzu syntax notes (validated on kuzu 0.11.3):
- ``* SHORTEST`` requires a lower bound of exactly 1 ("Lower bound of
  shortest/all_shortest path must be 1"). The vendored node queries use
  ``*2..{2d}``, but in the reified graph (Entity -> RelatesToNode_ -> Entity)
  path lengths strictly alternate node types: Entity destinations only exist at
  even depths >= 2 and RelatesToNode_ destinations at odd depths >= 1, so typing
  the destination makes ``SHORTEST 1..d`` equivalent to the vendored bounds.
- ``SHORTEST`` works mid-pattern after a fixed ``-[:MENTIONS]->`` hop.

These functions are drop-in replacements for the two vendored leg functions: the
signatures match, results parse through the same record helpers, and the
per-sub-query LIMIT (without a global cap across sub-queries) mirrors the
vendored behavior so rerank fan-out stays identical. Internal-layout drift is
guarded by ``graphiti_compat`` (exact version pin + signature probes, extended
with the helpers used here).
"""

from __future__ import annotations

from graphiti_core.driver.driver import GraphDriver, GraphProvider
from graphiti_core.edges import EntityEdge, get_entity_edge_from_record
from graphiti_core.models.edges.edge_db_queries import get_entity_edge_return_query
from graphiti_core.models.nodes.node_db_queries import get_entity_node_return_query
from graphiti_core.nodes import EntityNode, get_entity_node_from_record
from graphiti_core.search.search_filters import (
    SearchFilters,
    edge_search_filter_query_constructor,
    node_search_filter_query_constructor,
)

# Mirrors graphiti_core.search.search_utils.RELEVANT_SCHEMA_LIMIT (the vendored
# default for these legs); duplicated as a literal because importing it would add
# one more internal reliance for a constant.
_RELEVANT_SCHEMA_LIMIT = 10


def _require_kuzu(driver: GraphDriver, fn_name: str) -> None:
    """The SHORTEST rewrite is validated against Kuzu only; fail loud elsewhere."""
    if driver.provider != GraphProvider.KUZU:
        raise ValueError(
            f"{fn_name} is a Kuzu-specific rewrite (provider={driver.provider}); "
            "use graphiti_core.search.search_utils for other providers."
        )


def _dedup(origin_uuids: list[str]) -> list[str]:
    """Order-preserving origin dedup.

    The vendored functions UNWIND the origin list as-is; the eval pipeline can
    legitimately produce the same hub uuid several times (one per candidate edge),
    which multiplies the traversal for zero recall gain — the crashed LoCoMo run
    passed each speaker twice.
    """
    return list(dict.fromkeys(origin_uuids))


async def edge_bfs_search_shortest(
    driver: GraphDriver,
    bfs_origin_node_uuids: list[str] | None,
    bfs_max_depth: int,
    search_filter: SearchFilters,
    group_ids: list[str] | None = None,
    limit: int = _RELEVANT_SCHEMA_LIMIT,
) -> list[EntityEdge]:
    """Drop-in for ``search_utils.edge_bfs_search`` (Kuzu): facts within k hops.

    Same origin semantics as the vendored shape — Entity origins traverse
    ``RELATES_TO`` directly; Episodic origins enter through one ``MENTIONS`` hop
    when ``bfs_max_depth > 1``. An origin uuid of the "wrong" label simply matches
    nothing in that sub-query, exactly like the vendored UNWIND.
    """
    _require_kuzu(driver, "edge_bfs_search_shortest")
    if not bfs_origin_node_uuids or bfs_max_depth < 1:
        return []
    origins = _dedup(bfs_origin_node_uuids)

    filter_queries, filter_params = edge_search_filter_query_constructor(
        search_filter, GraphProvider.KUZU
    )
    if group_ids is not None:
        filter_queries.append("e.group_id IN $group_ids")
        filter_params["group_ids"] = group_ids
    filter_query = ""
    if filter_queries:
        filter_query = " WHERE " + (" AND ".join(filter_queries))

    # Vendored depth math: each semantic hop is 2 physical edges through the
    # reified RelatesToNode_, and fact nodes sit at odd depths.
    entity_depth = bfs_max_depth * 2 - 1
    match_queries = [
        f"""
        UNWIND $bfs_origin_node_uuids AS origin_uuid
        MATCH (origin:Entity {{uuid: origin_uuid}})-[:RELATES_TO* SHORTEST 1..{entity_depth}]->(e:RelatesToNode_)
        MATCH (n:Entity)-[:RELATES_TO]->(e)-[:RELATES_TO]->(m:Entity)
        """,
    ]
    if bfs_max_depth > 1:
        episodic_depth = (bfs_max_depth - 1) * 2 - 1
        match_queries.append(f"""
            UNWIND $bfs_origin_node_uuids AS origin_uuid
            MATCH (origin:Episodic {{uuid: origin_uuid}})-[:MENTIONS]->(:Entity)-[:RELATES_TO* SHORTEST 1..{episodic_depth}]->(e:RelatesToNode_)
            MATCH (n:Entity)-[:RELATES_TO]->(e)-[:RELATES_TO]->(m:Entity)
        """)

    records: list = []
    for match_query in match_queries:
        sub_records, _, _ = await driver.execute_query(
            match_query
            + filter_query
            + """
            RETURN DISTINCT
            """
            + get_entity_edge_return_query(GraphProvider.KUZU)
            + """
            LIMIT $limit
            """,
            bfs_origin_node_uuids=origins,
            limit=limit,
            **filter_params,
        )
        records.extend(sub_records)

    return [get_entity_edge_from_record(record, driver.provider) for record in records]


async def node_bfs_search_shortest(
    driver: GraphDriver,
    bfs_origin_node_uuids: list[str] | None,
    search_filter: SearchFilters,
    bfs_max_depth: int,
    group_ids: list[str] | None = None,
    limit: int = _RELEVANT_SCHEMA_LIMIT,
) -> list[EntityNode]:
    """Drop-in for ``search_utils.node_bfs_search`` (Kuzu): entities within k hops.

    Mirrors the vendored three sub-queries (Episodic 1-hop MENTIONS, Entity
    traversal, Episodic-through-Entity traversal) with the recursive segments
    switched to ``SHORTEST``. Lower bounds become 1 (Kuzu requirement) — see the
    module docstring for why that is equivalent to the vendored ``2..{2d}``.
    """
    _require_kuzu(driver, "node_bfs_search_shortest")
    if not bfs_origin_node_uuids or bfs_max_depth < 1:
        return []
    origins = _dedup(bfs_origin_node_uuids)

    filter_queries, filter_params = node_search_filter_query_constructor(
        search_filter, GraphProvider.KUZU
    )
    if group_ids is not None:
        filter_queries.append("n.group_id IN $group_ids")
        filter_queries.append("origin.group_id IN $group_ids")
        filter_params["group_ids"] = group_ids
    filter_query = ""
    if filter_queries:
        # The match queries below already carry a WHERE clause, so extra filters
        # append with AND (same composition as the vendored function).
        filter_query = " AND " + (" AND ".join(filter_queries))

    entity_depth = bfs_max_depth * 2
    match_queries = [
        # Direct mention — single fixed hop, no recursion: kept verbatim.
        """
        UNWIND $bfs_origin_node_uuids AS origin_uuid
        MATCH (origin:Episodic {uuid: origin_uuid})-[:MENTIONS]->(n:Entity)
        WHERE n.group_id = origin.group_id
        """,
        f"""
        UNWIND $bfs_origin_node_uuids AS origin_uuid
        MATCH (origin:Entity {{uuid: origin_uuid}})-[:RELATES_TO* SHORTEST 1..{entity_depth}]->(n:Entity)
        WHERE n.group_id = origin.group_id
        """,
    ]
    if bfs_max_depth > 1:
        episodic_depth = (bfs_max_depth - 1) * 2
        match_queries.append(f"""
            UNWIND $bfs_origin_node_uuids AS origin_uuid
            MATCH (origin:Episodic {{uuid: origin_uuid}})-[:MENTIONS]->(:Entity)-[:RELATES_TO* SHORTEST 1..{episodic_depth}]->(n:Entity)
            WHERE n.group_id = origin.group_id
        """)

    records: list = []
    for match_query in match_queries:
        sub_records, _, _ = await driver.execute_query(
            match_query
            + filter_query
            + """
            RETURN
            """
            + get_entity_node_return_query(GraphProvider.KUZU)
            + """
            LIMIT $limit
            """,
            bfs_origin_node_uuids=origins,
            limit=limit,
            **filter_params,
        )
        records.extend(sub_records)

    return [get_entity_node_from_record(record, driver.provider) for record in records]
