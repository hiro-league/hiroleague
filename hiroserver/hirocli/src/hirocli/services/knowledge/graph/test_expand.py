"""Tests for L3 graph expansion — entities → chunk_ids.

Builds a tiny Lina↔Omar↔Acme graph (the Example D shape) on a real Ladybug
store, then verifies:

- entities matched by canonical name resolve and pull their chunks
- entities matched by **alias** resolve (the bare "mom" → Sara case)
- k=1 expansion pulls in neighbors AND edge provenance
- missing graph DB yields a clean empty result (don't raise)
- empty / whitespace-only entity lists short-circuit
"""

from __future__ import annotations

import pytest

ladybug = pytest.importorskip("ladybug")
rapidfuzz = pytest.importorskip("rapidfuzz")

from .expand import GraphExpansion, expand_entities_to_chunk_ids  # noqa: E402
from .ladybug_adapter import LadybugGraphStore  # noqa: E402
from .store import GraphEdge, GraphNode, normalize_name  # noqa: E402


@pytest.fixture
def seeded_db(tmp_path):
    """A small graph: Lina --SPOUSE-- Omar --WORKS_AT-- Acme.

    Closes the seed store BEFORE yielding so ``expand_entities_to_chunk_ids``
    can open its own connection — Ladybug uses a per-file lock, so two open
    handles to the same DB collide (Error 33 ``Could not set lock on file``).
    Production usage opens once per call, which is the safe pattern.
    """
    db_path = tmp_path / "graph" / "ladybug.db"
    store = LadybugGraphStore.open(db_path)
    try:
        # Lina has an alias ('my sister') so we can test bare-mention expansion.
        store.upsert_node(
            GraphNode(
                id="p_lina",
                name="Lina",
                type="Person",
                normalized_name=normalize_name("Lina"),
                aliases=("my sister",),
                chunk_ids=("c_LINA_1",),
                document_ids=("d_1",),
            )
        )
        store.upsert_node(
            GraphNode(
                id="p_omar",
                name="Omar",
                type="Person",
                normalized_name=normalize_name("Omar"),
                chunk_ids=("c_OMAR_1",),
                document_ids=("d_1",),
            )
        )
        store.upsert_node(
            GraphNode(
                id="o_acme",
                name="Acme",
                type="Organization",
                normalized_name=normalize_name("Acme"),
                chunk_ids=("c_ACME_1",),
                document_ids=("d_2",),
            )
        )
        # Edges carry their OWN provenance (often the chunk asserting the
        # relation is what answers a relational query).
        store.upsert_edge(
            GraphEdge(
                id="e_lina_omar",
                source_id="p_lina",
                target_id="p_omar",
                rel_type="SPOUSE",
                chunk_ids=("c_LINA_OMAR_REL",),
                document_ids=("d_1",),
            )
        )
        store.upsert_edge(
            GraphEdge(
                id="e_omar_acme",
                source_id="p_omar",
                target_id="o_acme",
                rel_type="WORKS_AT",
                chunk_ids=("c_OMAR_ACME_REL",),
                document_ids=("d_2",),
            )
        )
    finally:
        # Release the lock BEFORE expand() tries to open the same file.
        store.close()
    yield db_path


@pytest.mark.asyncio
async def test_empty_entities_short_circuit(seeded_db) -> None:
    """No work, no chunks, no requests counted."""
    result = await expand_entities_to_chunk_ids(seeded_db, [])
    assert result == GraphExpansion(
        chunk_ids=(), nodes_touched=0, entities_resolved=0, entities_requested=0
    )


@pytest.mark.asyncio
async def test_whitespace_entities_short_circuit(seeded_db) -> None:
    result = await expand_entities_to_chunk_ids(seeded_db, ["", "  ", "\t"])
    assert result.chunk_ids == ()
    assert result.nodes_touched == 0


@pytest.mark.asyncio
async def test_missing_db_returns_empty(tmp_path) -> None:
    """The expected state for a workspace that hasn't opted into the L3 graph yet.
    MUST NOT raise — caller (the agent graph) falls back to flat search."""
    nonexistent = tmp_path / "never" / "ladybug.db"
    assert not nonexistent.exists()
    result = await expand_entities_to_chunk_ids(nonexistent, ["Lina"])
    assert result.chunk_ids == ()
    assert result.entities_requested == 1
    assert result.entities_resolved == 0


@pytest.mark.asyncio
async def test_canonical_name_match_expands_one_hop(seeded_db) -> None:
    """'Lina' → her node + Omar (1-hop) + the SPOUSE edge's chunk.
    Acme is *2* hops away — should NOT be included at k=1."""
    result = await expand_entities_to_chunk_ids(seeded_db, ["Lina"], k=1)
    assert result.entities_resolved == 1
    # Lina + Omar = 2 nodes touched
    assert result.nodes_touched == 2
    # Lina's own chunk + Omar's chunk + the SPOUSE edge's chunk
    expected = {"c_LINA_1", "c_OMAR_1", "c_LINA_OMAR_REL"}
    assert set(result.chunk_ids) == expected
    # Acme's chunk is 2 hops away — must NOT be in the set
    assert "c_ACME_1" not in result.chunk_ids
    assert "c_OMAR_ACME_REL" not in result.chunk_ids


@pytest.mark.asyncio
async def test_alias_match_resolves_to_canonical_node(seeded_db) -> None:
    """The Example D / bare-'mom' case: query says 'my sister', graph has Lina
    with alias 'my sister'. Expansion must find her and pull the same set."""
    via_canonical = await expand_entities_to_chunk_ids(seeded_db, ["Lina"], k=1)
    via_alias = await expand_entities_to_chunk_ids(seeded_db, ["my sister"], k=1)
    assert set(via_alias.chunk_ids) == set(via_canonical.chunk_ids)
    assert via_alias.entities_resolved == 1


@pytest.mark.asyncio
async def test_unknown_entity_silently_ignored(seeded_db) -> None:
    """An entity that doesn't exist in the graph contributes nothing — no raise,
    no false matches; mixed with a known entity still returns the known one's set."""
    result = await expand_entities_to_chunk_ids(
        seeded_db, ["NoSuchPerson", "Lina"], k=1
    )
    assert result.entities_requested == 2
    assert result.entities_resolved == 1  # only Lina matched
    assert "c_LINA_1" in result.chunk_ids


@pytest.mark.asyncio
async def test_two_hop_expansion_includes_grandchildren(seeded_db) -> None:
    """k=2: Lina → Omar → Acme. Acme should now be in the set."""
    result = await expand_entities_to_chunk_ids(seeded_db, ["Lina"], k=2)
    assert result.nodes_touched == 3  # Lina + Omar + Acme
    assert "c_ACME_1" in result.chunk_ids


@pytest.mark.asyncio
async def test_chunk_ids_are_sorted_deterministic(seeded_db) -> None:
    """Same input → same output ordering. Important because chunk_ids become
    a Qdrant filter key — deterministic order helps with caching/diffing."""
    a = await expand_entities_to_chunk_ids(seeded_db, ["Lina"], k=2)
    b = await expand_entities_to_chunk_ids(seeded_db, ["Lina"], k=2)
    assert a.chunk_ids == b.chunk_ids
    assert list(a.chunk_ids) == sorted(a.chunk_ids)


@pytest.mark.asyncio
async def test_dedupes_repeated_mentions(seeded_db) -> None:
    """LLM-extracted entities[] may include the same name twice — must dedupe."""
    result = await expand_entities_to_chunk_ids(seeded_db, ["Lina", "Lina ", "lina"], k=1)
    # Three raw mentions but only one canonical entity_requested after dedup.
    # (Our dedupe is by raw text post-strip; 'Lina' and 'Lina ' collapse,
    # but 'lina' is a different raw string. Both resolve to Lina though.)
    assert result.entities_resolved >= 1
    assert result.nodes_touched == 2  # Lina + Omar, not duplicated
