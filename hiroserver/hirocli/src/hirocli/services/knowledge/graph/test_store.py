"""Smoke tests for the L3 prototype GraphStore + LadybugDB adapter.

Skipped automatically when the ``ladybug`` package isn't installed yet — keeps
the test suite green during the brief window between ``uv add ladybug`` and the
next ``uv sync`` (e.g. while the dev server is still holding ``hiro.exe``).
"""

from __future__ import annotations

import pytest

from .store import GraphEdge, GraphNode, GraphStore, normalize_name

# Skip the whole module if Ladybug isn't installed yet — adapter still imports
# cleanly because its ``ladybug`` import is lazy inside ``LadybugGraphStore.open``.
ladybug = pytest.importorskip("ladybug")

from .ladybug_adapter import LadybugGraphStore  # noqa: E402 — after importorskip


# ---------------------------------------------------------------------------
# normalize_name — pure function, no Ladybug needed (runs even if skipped above)
# ---------------------------------------------------------------------------


def test_normalize_name_lowercases_and_strips() -> None:
    assert normalize_name("  Maya  ") == "maya"
    assert normalize_name("New\tYork  City") == "new york city"


def test_normalize_name_folds_diacritics_across_languages() -> None:
    """Language-agnostic fold via NFKD + strip-Mn + casefold — NOT an Arabic-
    specific table. Same mechanism collapses accents in any script."""
    # Arabic alef variants → bare alef
    assert normalize_name("أحمد") == normalize_name("احمد")
    assert normalize_name("إيمان") == normalize_name("ايمان")
    assert normalize_name("آدم") == normalize_name("ادم")
    # French accents
    assert normalize_name("François") == normalize_name("francois")
    assert normalize_name("Café") == normalize_name("cafe")
    # Spanish tilde + acute
    assert normalize_name("España") == normalize_name("espana")
    assert normalize_name("José") == normalize_name("jose")
    # Vietnamese tones (note caveat in docstring — included to lock in current behavior)
    assert normalize_name("Phở") == normalize_name("pho")
    # Combining marks on a Latin base
    assert normalize_name("naïve") == "naive"


def test_normalize_name_uses_casefold_not_lower() -> None:
    """German ß folds to 'ss' under casefold(); str.lower() leaves it as ß.
    This catch is exactly why we use casefold() — generic, not per-language."""
    assert normalize_name("Straße") == normalize_name("strasse")
    assert normalize_name("Straße") == "strasse"


def test_normalize_name_handles_compatibility_forms() -> None:
    """NFKD normalizes compatibility-equivalent codepoints (full-width digits,
    ligatures) so external sources writing in different encodings still match."""
    # Full-width 'A' (U+FF21) folds to ASCII 'a'
    assert normalize_name("Ａcme") == normalize_name("acme")
    # Latin ligature 'ﬁ' (U+FB01) → 'fi'
    assert normalize_name("ﬁreplace") == normalize_name("fireplace")


def test_normalize_name_empty_safe() -> None:
    assert normalize_name("") == ""
    assert normalize_name("   ") == ""


# ---------------------------------------------------------------------------
# LadybugGraphStore — round-trip a small graph
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "graph" / "ladybug.db"
    s = LadybugGraphStore.open(db_path)
    try:
        yield s
    finally:
        s.close()


def _node(id_: str, name: str, type_: str = "Person", **extras) -> GraphNode:
    return GraphNode(
        id=id_,
        name=name,
        type=type_,
        normalized_name=normalize_name(name),
        chunk_ids=tuple(extras.pop("chunk_ids", ())),
        document_ids=tuple(extras.pop("document_ids", ())),
        aliases=tuple(extras.pop("aliases", ())),
        attrs=extras.pop("attrs", {}),
    )


def _edge(id_: str, src: str, tgt: str, rel: str, **extras) -> GraphEdge:
    return GraphEdge(
        id=id_,
        source_id=src,
        target_id=tgt,
        rel_type=rel,
        chunk_ids=tuple(extras.pop("chunk_ids", ())),
        document_ids=tuple(extras.pop("document_ids", ())),
    )


def test_store_satisfies_graphstore_protocol(store: LadybugGraphStore) -> None:
    # Runtime-checkable Protocol catches accidental signature drift in the adapter.
    assert isinstance(store, GraphStore)


def test_upsert_and_get_node(store: LadybugGraphStore) -> None:
    store.upsert_node(_node("p_maya", "Maya", chunk_ids=("c_1",), document_ids=("d_1",)))
    got = store.get_node("p_maya")
    assert got is not None
    assert got.name == "Maya"
    assert got.normalized_name == "maya"
    assert got.type == "Person"
    assert "c_1" in got.chunk_ids
    assert "d_1" in got.document_ids


def test_upsert_node_merges_provenance(store: LadybugGraphStore) -> None:
    """Re-ingest of the same entity from a NEW chunk must MERGE provenance,
    not erase the prior chunk_ids — F5 inline-provenance invariant."""
    store.upsert_node(_node("p_maya", "Maya", chunk_ids=("c_1",), document_ids=("d_1",)))
    store.upsert_node(_node("p_maya", "Maya", chunk_ids=("c_2",), document_ids=("d_1", "d_2")))
    got = store.get_node("p_maya")
    assert got is not None
    assert set(got.chunk_ids) == {"c_1", "c_2"}
    assert set(got.document_ids) == {"d_1", "d_2"}


def test_find_by_name_exact_finds_one(store: LadybugGraphStore) -> None:
    store.upsert_node(_node("p_lina", "Lina"))
    store.upsert_node(_node("p_omar", "Omar"))
    hits = store.find_by_name_exact("lina")
    assert [n.id for n in hits] == ["p_lina"]
    assert store.find_by_name_exact("nobody") == []


def test_find_by_name_exact_returns_all_collisions(store: LadybugGraphStore) -> None:
    """Two-Ahmeds — exact match returns BOTH so the resolver knows to escalate
    to LLM disambiguation (Example C in the prototype plan)."""
    store.upsert_node(_node("p_ahmed_cousin", "Ahmed"))
    store.upsert_node(_node("p_ahmed_coworker", "Ahmed"))
    hits = store.find_by_name_exact("ahmed")
    assert {n.id for n in hits} == {"p_ahmed_cousin", "p_ahmed_coworker"}


def test_find_candidates_by_name_substring(store: LadybugGraphStore) -> None:
    store.upsert_node(_node("p_selim", "Selim"))
    store.upsert_node(_node("p_selima", "Selima"))
    store.upsert_node(_node("p_lina", "Lina"))
    hits = store.find_candidates_by_name("seli", limit=10)
    assert {n.id for n in hits} == {"p_selim", "p_selima"}


def test_upsert_edge_and_neighbors_1hop(store: LadybugGraphStore) -> None:
    # Lina --SPOUSE-- Omar --WORKS_AT-- Acme  (the Example D shape)
    store.upsert_node(_node("p_lina", "Lina"))
    store.upsert_node(_node("p_omar", "Omar"))
    store.upsert_node(_node("o_acme", "Acme", type_="Organization"))
    store.upsert_edge(_edge("e_lo", "p_lina", "p_omar", "SPOUSE", chunk_ids=("c_5",)))
    store.upsert_edge(_edge("e_ow", "p_omar", "o_acme", "WORKS_AT", chunk_ids=("c_7",)))

    one_hop = {n.id for n in store.neighbors("p_lina", k=1)}
    assert one_hop == {"p_omar"}

    two_hop = {n.id for n in store.neighbors("p_lina", k=2)}
    assert two_hop == {"p_omar", "o_acme"}


def test_edges_by_direction(store: LadybugGraphStore) -> None:
    store.upsert_node(_node("p_lina", "Lina"))
    store.upsert_node(_node("p_omar", "Omar"))
    store.upsert_edge(_edge("e_lo", "p_lina", "p_omar", "SPOUSE", chunk_ids=("c_5",)))
    out = store.edges("p_lina", direction="out")
    assert [e.id for e in out] == ["e_lo"]
    assert store.edges("p_lina", direction="in") == []
    both = store.edges("p_omar", direction="both")
    assert [e.id for e in both] == ["e_lo"]


def test_edge_upsert_merges_provenance(store: LadybugGraphStore) -> None:
    store.upsert_node(_node("p_lina", "Lina"))
    store.upsert_node(_node("p_omar", "Omar"))
    store.upsert_edge(_edge("e_lo", "p_lina", "p_omar", "SPOUSE", chunk_ids=("c_5",)))
    store.upsert_edge(_edge("e_lo", "p_lina", "p_omar", "SPOUSE", chunk_ids=("c_9",)))
    [e] = store.edges("p_lina", direction="out")
    assert set(e.chunk_ids) == {"c_5", "c_9"}


def test_close_is_idempotent(tmp_path) -> None:
    s = LadybugGraphStore.open(tmp_path / "graph" / "ladybug.db")
    s.close()
    s.close()  # second call must not raise
