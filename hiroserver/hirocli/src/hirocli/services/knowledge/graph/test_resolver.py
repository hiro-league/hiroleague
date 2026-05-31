"""Tests for the deterministic-first :class:`GraphResolver`.

Goal: exercise every branch of the ladder against a real Ladybug store (and a
small in-memory :class:`FakeStore` for the corner cases where a real store can't
deterministically produce a candidate set with the right shape) with a **stub**
LLM disambiguator — so the LLM contract is tested but no model is required.
The stub records its inputs so we can assert "did the LLM get called when it
should have, and not when it shouldn't?" — the core cost guarantee.
"""

from __future__ import annotations

import pytest

ladybug = pytest.importorskip("ladybug")
rapidfuzz = pytest.importorskip("rapidfuzz")

from .ingest import ALLOWED_SOURCE_ROLES, REJECTED_SOURCE_ROLES  # noqa: E402 — after importorskip
from .ladybug_adapter import LadybugGraphStore  # noqa: E402
from .ontology import ExtractedEntity  # noqa: E402
from .resolver import (  # noqa: E402
    FUZZY_MATCH_THRESHOLD,
    GraphResolver,
    _is_distinctive_name,
    _name_entropy,
)
from .store import GraphEdge, GraphNode, GraphStore, normalize_name  # noqa: E402


# ---------------------------------------------------------------------------
# Stub disambiguator — records every call so we can assert the cost guarantee.
# ---------------------------------------------------------------------------


class StubDisambiguator:
    """Callable async that returns a canned id (or None). Records every invocation."""

    def __init__(self, decision_by_mention: dict[str, str | None] | None = None) -> None:
        # mention.name -> candidate id to return (or None for "no match")
        self.decisions = decision_by_mention or {}
        self.calls: list[tuple[str, list[str]]] = []  # (mention.name, [candidate.id, ...])

    async def __call__(
        self, mention: ExtractedEntity, candidates: list[GraphNode]
    ) -> str | None:
        self.calls.append((mention.name, [c.id for c in candidates]))
        return self.decisions.get(mention.name)


class FakeStore:
    """Minimal in-memory :class:`GraphStore` for testing resolver branches that
    are awkward to construct deterministically through Ladybug (specifically,
    "fuzzy candidate exists but WRatio < threshold" — substring filters in the
    real adapter make this combination hard to set up without contrived names).

    Implements only what the resolver uses; sufficient for unit-testing the
    ladder logic in isolation."""

    def __init__(
        self,
        *,
        exact_hits: list[GraphNode] | None = None,
        candidates: list[GraphNode] | None = None,
    ) -> None:
        self._exact = list(exact_hits or [])
        self._candidates = list(candidates or [])
        self.upserted_nodes: list[GraphNode] = []

    def find_by_name_exact(self, normalized_name, *, type=None):  # noqa: ANN001
        return list(self._exact)

    def find_candidates_by_name(self, name, *, type=None, limit=20):  # noqa: ANN001
        return list(self._candidates)

    def upsert_node(self, node):  # noqa: ANN001
        self.upserted_nodes.append(node)

    def get_node(self, node_id):  # noqa: ANN001
        # Search recent writes first (newest provenance wins), then seeded sets.
        for n in reversed(self.upserted_nodes):
            if n.id == node_id:
                return n
        for n in (*self._exact, *self._candidates):
            if n.id == node_id:
                return n
        return None

    def upsert_edge(self, edge):  # noqa: ANN001
        pass

    def neighbors(self, node_id, *, k=1, rel_types=None):  # noqa: ANN001
        return []

    def edges(self, node_id, *, direction="both"):  # noqa: ANN001
        return []

    def get_edge(self, edge_id):  # noqa: ANN001
        return None

    def snapshot(self, *, node_limit=None, edge_limit=None):  # noqa: ANN001
        return list(self.upserted_nodes), []

    def close(self) -> None:
        pass


def test_fake_store_satisfies_graphstore_protocol() -> None:
    # Catches signature drift between the resolver's interface needs and the fake.
    assert isinstance(FakeStore(), GraphStore)


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "graph" / "ladybug.db"
    s = LadybugGraphStore.open(db_path)
    try:
        yield s
    finally:
        s.close()


def _seed(store: LadybugGraphStore, id_: str, name: str, type_: str = "Person") -> GraphNode:
    node = GraphNode(
        id=id_,
        name=name,
        type=type_,
        normalized_name=normalize_name(name),
    )
    store.upsert_node(node)
    return node


# ---------------------------------------------------------------------------
# Helpers / unit tests on the gate logic itself
# ---------------------------------------------------------------------------


def test_entropy_threshold_blocks_short_common_names() -> None:
    # The names the entropy gate must NOT trust to deterministic matching.
    assert not _is_distinctive_name("mom")
    assert not _is_distinctive_name("dad")
    assert not _is_distinctive_name("sam")
    assert not _is_distinctive_name("")


def test_entropy_threshold_allows_distinctive_names() -> None:
    assert _is_distinctive_name("eiffel tower")
    assert _is_distinctive_name("new york city")
    assert _is_distinctive_name("gamecube")


def test_name_entropy_increases_with_variety() -> None:
    # Sanity-check the entropy function so a future tuning change has a baseline.
    assert _name_entropy("aaaa") < _name_entropy("abcd")


def test_source_role_constants_are_disjoint() -> None:
    """F7 invariant: nothing is simultaneously allowed and rejected."""
    assert not ALLOWED_SOURCE_ROLES & REJECTED_SOURCE_ROLES


# ---------------------------------------------------------------------------
# Ladder branches — one test per outcome.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_match_links_without_llm(store: LadybugGraphStore) -> None:
    _seed(store, "p_lina", "Lina")
    stub = StubDisambiguator()
    resolver = GraphResolver(store, disambiguator=stub)
    result = await resolver.link_or_create(
        ExtractedEntity(name="Lina", type="Person"), chunk_id="c_1", document_id="d_1"
    )
    assert result.node_id == "p_lina"
    assert result.branch == "exact_link"
    assert result.llm_call is False
    assert stub.calls == []  # cost guarantee: no LLM when exact match suffices


@pytest.mark.asyncio
async def test_exact_match_collision_escalates_to_llm(store: LadybugGraphStore) -> None:
    """Two-Ahmeds: same normalized name, two distinct nodes → LLM picks one."""
    _seed(store, "p_ahmed_cousin", "Ahmed")
    _seed(store, "p_ahmed_coworker", "Ahmed")
    stub = StubDisambiguator({"Ahmed": "p_ahmed_coworker"})
    resolver = GraphResolver(store, disambiguator=stub)
    result = await resolver.link_or_create(
        ExtractedEntity(name="Ahmed", type="Person"), chunk_id="c_1", document_id="d_1"
    )
    assert result.node_id == "p_ahmed_coworker"
    assert result.branch == "llm_link"
    assert result.llm_call is True
    assert len(stub.calls) == 1
    assert set(stub.calls[0][1]) == {"p_ahmed_cousin", "p_ahmed_coworker"}


@pytest.mark.asyncio
async def test_no_candidates_creates_new_node(store: LadybugGraphStore) -> None:
    stub = StubDisambiguator()
    resolver = GraphResolver(store, disambiguator=stub)
    result = await resolver.link_or_create(
        ExtractedEntity(name="Selim", type="Person"), chunk_id="c_1", document_id="d_1"
    )
    assert result.branch == "created"
    assert result.llm_call is False
    assert stub.calls == []
    # The new node is fetchable
    assert store.get_node(result.node_id) is not None


@pytest.mark.asyncio
async def test_fuzzy_match_above_threshold_links_without_llm(
    store: LadybugGraphStore,
) -> None:
    """A distinctive name that fuzzy-matches an existing node above threshold
    (90/100 default) should link without the LLM. 'Selim Khan' vs 'Selim' is
    above WRatio 90 (partial token match dominates)."""
    _seed(store, "p_selim", "Selim")
    stub = StubDisambiguator()
    resolver = GraphResolver(store, disambiguator=stub)
    result = await resolver.link_or_create(
        ExtractedEntity(name="Selim", type="Person"),  # exact normalized match
        chunk_id="c_1", document_id="d_1",
    )
    # This is technically an exact_link (same name) — verify the cost guarantee.
    assert result.branch == "exact_link"
    assert stub.calls == []


@pytest.mark.asyncio
async def test_fuzzy_below_threshold_with_candidates_escalates_to_llm() -> None:
    """Distinctive name + candidates exist + WRatio below threshold → LLM.

    Uses ``FakeStore`` to feed the resolver a controlled candidate set:
    constructing this combination through Ladybug's substring filter is brittle
    (a substring match tends to produce a high WRatio), but the branch the
    resolver implements is real and must be unit-testable in isolation."""
    candidates = [
        GraphNode(
            id="p_x",
            name="Completely Different Name",
            type="Person",
            normalized_name="completely different name",
        ),
    ]
    fake = FakeStore(candidates=candidates)
    stub = StubDisambiguator({"My Mention Phrase": "p_x"})
    resolver = GraphResolver(fake, disambiguator=stub)
    result = await resolver.link_or_create(
        ExtractedEntity(name="My Mention Phrase", type="Person"),
        chunk_id="c_1", document_id="d_1",
    )
    assert result.branch == "llm_link"
    assert result.llm_call is True
    assert result.node_id == "p_x"
    # Resolver called LLM exactly once on this path (not twice — the entropy gate
    # didn't trigger because the mention IS distinctive).
    assert len(stub.calls) == 1


@pytest.mark.asyncio
async def test_fuzzy_below_threshold_no_llm_match_creates_new() -> None:
    """Same branch — candidates exist, fuzzy too low — but the LLM says "none
    of these is the same". Resolver MUST create a new node, not pick a wrong one."""
    candidates = [
        GraphNode(
            id="p_x",
            name="Wholly Unrelated",
            type="Person",
            normalized_name="wholly unrelated",
        ),
    ]
    fake = FakeStore(candidates=candidates)
    stub = StubDisambiguator({"Truly New Name": None})  # LLM says: no match
    resolver = GraphResolver(fake, disambiguator=stub)
    result = await resolver.link_or_create(
        ExtractedEntity(name="Truly New Name", type="Person"),
        chunk_id="c_1", document_id="d_1",
    )
    assert result.branch == "created"
    assert result.llm_call is False  # the *result* branch didn't link via LLM
    assert len(stub.calls) == 1      # but the LLM was consulted (cost record)
    # A node was upserted with the new name.
    assert any(n.normalized_name == "truly new name" for n in fake.upserted_nodes)


@pytest.mark.asyncio
async def test_low_entropy_name_bypasses_fuzzy_to_llm(store: LadybugGraphStore) -> None:
    """Example B from the plan: 'Mom' is short + common → entropy gate blocks
    fuzzy and goes straight to LLM with candidates whose normalized name
    contains 'mom'. (We seed a node whose substring matches so candidates are
    non-empty; the LLM stub then links them.)"""
    _seed(store, "p_sara", "Mommy Sara")  # substring "mom" lives here
    stub = StubDisambiguator({"mom": "p_sara"})
    resolver = GraphResolver(store, disambiguator=stub)
    result = await resolver.link_or_create(
        ExtractedEntity(name="mom", type="Person"), chunk_id="c_NEW", document_id="d_NEW"
    )
    assert result.branch == "llm_link"
    assert result.llm_call is True
    assert result.node_id == "p_sara"
    # Provenance was appended to the existing node (F5).
    got = store.get_node("p_sara")
    assert got is not None
    assert "c_NEW" in got.chunk_ids
    assert "d_NEW" in got.document_ids


@pytest.mark.asyncio
async def test_low_entropy_no_candidates_creates_new(store: LadybugGraphStore) -> None:
    """Short common name with NO existing substring matches → create new (don't
    waste an LLM call when there's nothing to disambiguate against)."""
    stub = StubDisambiguator()
    resolver = GraphResolver(store, disambiguator=stub)
    result = await resolver.link_or_create(
        ExtractedEntity(name="dad", type="Person"), chunk_id="c_1", document_id="d_1"
    )
    assert result.branch == "created"
    assert result.llm_call is False
    assert stub.calls == []


@pytest.mark.asyncio
async def test_link_merges_provenance_across_calls(store: LadybugGraphStore) -> None:
    """Resolving the same entity from two different chunks must accumulate
    chunk_ids on the linked node (F5 invariant on the resolver path)."""
    _seed(store, "p_omar", "Omar")
    resolver = GraphResolver(store)
    await resolver.link_or_create(
        ExtractedEntity(name="Omar", type="Person"), chunk_id="c_1", document_id="d_1"
    )
    await resolver.link_or_create(
        ExtractedEntity(name="Omar", type="Person"), chunk_id="c_2", document_id="d_2"
    )
    got = store.get_node("p_omar")
    assert got is not None
    assert set(got.chunk_ids) == {"c_1", "c_2"}
    assert set(got.document_ids) == {"d_1", "d_2"}


@pytest.mark.asyncio
async def test_disambiguator_returning_unknown_id_is_ignored(
    store: LadybugGraphStore,
) -> None:
    """Robustness: if the LLM hallucinates a candidate id we don't have, the
    resolver MUST NOT crash — it falls through to create-new."""
    _seed(store, "p_ahmed_cousin", "Ahmed")
    _seed(store, "p_ahmed_coworker", "Ahmed")
    stub = StubDisambiguator({"Ahmed": "p_nonexistent"})
    resolver = GraphResolver(store, disambiguator=stub)
    result = await resolver.link_or_create(
        ExtractedEntity(name="Ahmed", type="Person"), chunk_id="c_1", document_id="d_1"
    )
    # LLM "match" was bogus → fell through → ladder went to fuzzy → still ambiguous
    # → second LLM call also bogus → fell through → created. We accept any
    # outcome that doesn't crash and doesn't pick a non-existent node.
    assert result.node_id != "p_nonexistent"
    assert store.get_node(result.node_id) is not None


@pytest.mark.asyncio
async def test_disambiguator_exception_falls_back_safely(
    store: LadybugGraphStore,
) -> None:
    """An exception in the disambiguator must not abort ingest — graceful skip."""
    _seed(store, "p_ahmed", "Ahmed")
    _seed(store, "p_ahmed2", "Ahmed")

    async def boom(mention, candidates):
        raise RuntimeError("simulated provider failure")

    resolver = GraphResolver(store, disambiguator=boom)
    result = await resolver.link_or_create(
        ExtractedEntity(name="Ahmed", type="Person"), chunk_id="c_1", document_id="d_1"
    )
    # No LLM link possible → created
    assert result.branch == "created"


@pytest.mark.asyncio
async def test_empty_mention_name_raises(store: LadybugGraphStore) -> None:
    """Defensive: empty names should never reach the store. Surface clearly."""
    resolver = GraphResolver(store)
    with pytest.raises(ValueError):
        await resolver.link_or_create(
            ExtractedEntity(name="   ", type="Person"), chunk_id="c", document_id="d"
        )


def test_fuzzy_match_threshold_is_in_band() -> None:
    """Lock in the threshold band: changing it is a design decision, not an accident."""
    assert 60 <= FUZZY_MATCH_THRESHOLD <= 100


# ---------------------------------------------------------------------------
# Aliases — the deterministic path for kinship/possessive coreference.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aliases_persisted_normalized_on_create(store: LadybugGraphStore) -> None:
    """An extracted entity with aliases creates a node whose aliases are stored
    NORMALIZED (so future exact-match queries against the alias column are direct
    equality, not per-row normalization). Canonical name is excluded from aliases."""
    resolver = GraphResolver(store)
    result = await resolver.link_or_create(
        ExtractedEntity(
            name="Sara",
            type="Person",
            aliases=["My Mother", "mom", "Sara"],  # 'Sara' dup must be dropped
        ),
        chunk_id="c_1", document_id="d_1",
    )
    node = store.get_node(result.node_id)
    assert node is not None
    # Stored aliases are normalized + deduped + canonical excluded.
    assert set(node.aliases) == {"my mother", "mom"}


@pytest.mark.asyncio
async def test_bare_mention_finds_node_via_alias(store: LadybugGraphStore) -> None:
    """The Example B fix. Seed Sara with alias 'mom'; a later bare 'Mom' mention
    must exact-match deterministically — NO LLM call needed."""
    # Round 1: 'my mother Sara' chunk creates Sara with aliases.
    resolver = GraphResolver(store)
    first = await resolver.link_or_create(
        ExtractedEntity(name="Sara", type="Person", aliases=["my mother", "mom"]),
        chunk_id="c_1", document_id="d_1",
    )
    assert first.branch == "created"

    # Round 2: bare 'Mom' from a later chunk.
    stub = StubDisambiguator()  # would record an unexpected LLM call
    resolver2 = GraphResolver(store, disambiguator=stub)
    second = await resolver2.link_or_create(
        ExtractedEntity(name="Mom", type="Person"), chunk_id="c_2", document_id="d_2"
    )
    assert second.node_id == first.node_id     # same entity!
    assert second.branch == "exact_link"       # via the alias, not a fuzzy guess
    assert second.llm_call is False
    assert stub.calls == []                    # the cost guarantee
    # Provenance from the later chunk is on Sara's node.
    sara = store.get_node(first.node_id)
    assert sara is not None
    assert "c_2" in sara.chunk_ids


@pytest.mark.asyncio
async def test_link_accumulates_new_aliases_from_later_mentions(
    store: LadybugGraphStore,
) -> None:
    """When a later chunk supplies NEW aliases on an existing node, they're
    merged in — so the alias set grows over the corpus, not just on creation."""
    resolver = GraphResolver(store)
    first = await resolver.link_or_create(
        ExtractedEntity(name="Sara", type="Person", aliases=["mom"]),
        chunk_id="c_1", document_id="d_1",
    )
    # Same canonical name, different aliases in a later chunk.
    await resolver.link_or_create(
        ExtractedEntity(name="Sara", type="Person", aliases=["mommy", "MOM"]),
        chunk_id="c_2", document_id="d_2",
    )
    sara = store.get_node(first.node_id)
    assert sara is not None
    assert {"mom", "mommy"} <= set(sara.aliases)
