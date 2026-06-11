"""Parity tests for the SHORTEST-path BFS rewrite (``graphiti_bfs``).

The rewrite must return the **same result sets** as graphiti-core's vendored
all-paths fallbacks (``search_utils.edge_bfs_search`` / ``node_bfs_search``) —
it only changes *how* the reachable set is computed (linear-memory SHORTEST
traversal instead of exponential path enumeration; see
docs/kuzu-bfs-path-explosion-design.md). Runs against a real in-memory Kuzu
database so the Cypher (including the ``* SHORTEST`` syntax) is exercised for
real, guarding both parity and kuzu-version drift.

Fixture graph (group ``g``): a chain ``O -> A -> B -> C`` (one new fact per
hop), a cycle ``O -> H -> M1 -> O`` (exercises revisits, where all-paths
enumeration blows up), an episode ``EP`` mentioning ``O``, and a disconnected
second group ``h`` (``P -> Q``) for group filtering.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from graphiti_core.driver.driver import GraphProvider
from graphiti_core.driver.kuzu_driver import KuzuDriver
from graphiti_core.search import search_utils
from graphiti_core.search.search_filters import SearchFilters

from hirocli.services.knowledge.graph.graphiti_bfs import (
    edge_bfs_search_shortest,
    node_bfs_search_shortest,
)

_TS = "timestamp('2024-01-01 00:00:00')"


async def _entity(driver: KuzuDriver, uuid: str, group: str) -> None:
    await driver.execute_query(
        f"CREATE (:Entity {{uuid: '{uuid}', name: '{uuid}', group_id: '{group}', "
        f"labels: ['Entity'], created_at: {_TS}, summary: ''}})"
    )


async def _fact(driver: KuzuDriver, uuid: str, src: str, dst: str, group: str) -> None:
    """One reified fact edge: (src)-[:RELATES_TO]->(uuid)-[:RELATES_TO]->(dst)."""
    await driver.execute_query(
        f"CREATE (:RelatesToNode_ {{uuid: '{uuid}', name: '{uuid}', fact: '{uuid}', "
        f"group_id: '{group}', created_at: {_TS}, episodes: []}})"
    )
    await driver.execute_query(
        f"MATCH (a:Entity {{uuid: '{src}'}}), (r:RelatesToNode_ {{uuid: '{uuid}'}}) "
        f"CREATE (a)-[:RELATES_TO]->(r)"
    )
    await driver.execute_query(
        f"MATCH (r:RelatesToNode_ {{uuid: '{uuid}'}}), (b:Entity {{uuid: '{dst}'}}) "
        f"CREATE (r)-[:RELATES_TO]->(b)"
    )


async def _seed() -> KuzuDriver:
    driver = KuzuDriver(":memory:")
    for ent in ("O", "A", "B", "C", "H", "M1"):
        await _entity(driver, ent, "g")
    for ent in ("P", "Q"):
        await _entity(driver, ent, "h")
    # Chain: each depth level adds exactly one new fact.
    await _fact(driver, "r1", "O", "A", "g")
    await _fact(driver, "r2", "A", "B", "g")
    await _fact(driver, "r3", "B", "C", "g")
    # Cycle back to the origin: the all-paths fallback re-enumerates through it.
    await _fact(driver, "rh", "O", "H", "g")
    await _fact(driver, "rm", "H", "M1", "g")
    await _fact(driver, "rc", "M1", "O", "g")
    # Disconnected second group.
    await _fact(driver, "rp", "P", "Q", "h")
    # Episode mentioning the origin (Episodic-origin sub-queries).
    await driver.execute_query(
        f"CREATE (:Episodic {{uuid: 'EP', group_id: 'g', created_at: {_TS}, "
        f"name: 'EP', source: 'message', source_description: '', content: '', "
        f"valid_at: {_TS}, entity_edges: []}})"
    )
    await driver.execute_query(
        "MATCH (ep:Episodic {uuid: 'EP'}), (o:Entity {uuid: 'O'}) "
        "CREATE (ep)-[:MENTIONS]->(o)"
    )
    return driver


# Origins include a duplicate on purpose: the crashed LoCoMo run passed each hub
# origin twice, and the rewrite dedups them — results must be unaffected.
_ORIGINS = ["O", "EP", "O"]


@pytest.mark.asyncio
@pytest.mark.parametrize("depth", [1, 2, 3])
async def test_edge_bfs_parity(depth: int) -> None:
    driver = await _seed()
    vendored = await search_utils.edge_bfs_search(
        driver, _ORIGINS, depth, SearchFilters(), ["g"], limit=100
    )
    ours = await edge_bfs_search_shortest(
        driver, _ORIGINS, depth, SearchFilters(), ["g"], limit=100
    )
    assert {e.uuid for e in ours} == {e.uuid for e in vendored}


@pytest.mark.asyncio
@pytest.mark.parametrize("depth", [1, 2, 3])
async def test_node_bfs_parity(depth: int) -> None:
    driver = await _seed()
    vendored = await search_utils.node_bfs_search(
        driver, _ORIGINS, SearchFilters(), depth, ["g"], limit=100
    )
    ours = await node_bfs_search_shortest(
        driver, _ORIGINS, SearchFilters(), depth, ["g"], limit=100
    )
    assert {n.uuid for n in ours} == {n.uuid for n in vendored}


@pytest.mark.asyncio
async def test_edge_bfs_expected_frontier() -> None:
    """Pin the actual hop semantics (not just parity): one new fact per hop level."""
    driver = await _seed()
    by_depth = {}
    for depth in (1, 2, 3):
        edges = await edge_bfs_search_shortest(
            driver, ["O"], depth, SearchFilters(), ["g"], limit=100
        )
        by_depth[depth] = {e.uuid for e in edges}
    assert by_depth[1] == {"r1", "rh"}
    assert by_depth[2] == {"r1", "rh", "r2", "rm"}
    assert by_depth[3] == {"r1", "rh", "r2", "rm", "r3", "rc"}


@pytest.mark.asyncio
async def test_group_filter_excludes_other_partitions() -> None:
    driver = await _seed()
    edges = await edge_bfs_search_shortest(
        driver, ["O"], 3, SearchFilters(), ["h"], limit=100
    )
    assert edges == []
    nodes = await node_bfs_search_shortest(
        driver, ["O"], SearchFilters(), 3, ["h"], limit=100
    )
    assert nodes == []


@pytest.mark.asyncio
async def test_empty_origins_and_depth_guards() -> None:
    driver = await _seed()
    assert await edge_bfs_search_shortest(driver, None, 2, SearchFilters(), ["g"]) == []
    assert await edge_bfs_search_shortest(driver, [], 2, SearchFilters(), ["g"]) == []
    assert await node_bfs_search_shortest(driver, ["O"], SearchFilters(), 0, ["g"]) == []


@pytest.mark.asyncio
async def test_non_kuzu_provider_rejected() -> None:
    fake = SimpleNamespace(provider=GraphProvider.NEO4J)
    with pytest.raises(ValueError, match="Kuzu-specific"):
        await edge_bfs_search_shortest(fake, ["O"], 2, SearchFilters(), ["g"])
    with pytest.raises(ValueError, match="Kuzu-specific"):
        await node_bfs_search_shortest(fake, ["O"], SearchFilters(), 2, ["g"])
