"""Same hits as before the engine moved into the library: a pinned hybrid search, network-free.

A tiny Qdrant collection in a tmp dir, indexed through ``KnowledgeVectorStore`` with a deterministic dense embedder
(hashed bag of words) and a deterministic sparse one (hashed term counts). The expected (ord, score) lists were taken
from the core's ``services/knowledge/vector_store.py`` before the move; the RRF fusion, the explain path's in-process
fusion and the dense-only cosine path must keep giving exactly these.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest

from hiro_memory.knowledge.vector_store import KnowledgeVectorStore


def _h(word: str) -> int:
    return int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)


class _HashDense:
    dimension = 16

    def embed_texts(self, texts):
        out = []
        for text in texts:
            vec = [0.0] * self.dimension
            for word in text.lower().split():
                vec[_h(word) % self.dimension] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


def _hash_sparse(text: str):
    counts: dict[int, float] = {}
    for word in text.lower().split():
        idx = _h(word) % 1000
        counts[idx] = counts.get(idx, 0.0) + 1.0
    idx = sorted(counts)
    return (idx, [counts[i] for i in idx])


_CHUNKS = [
    "selim attended a private school in beirut",
    "the exams are in june and selim studies",
    "water the lemon tree every tuesday",
    "hiro speaks through the camera speakers",
    "olive trees and a lemon tree in the garden",
]

# (mode, query) → [(ord, score)] from the code before the move.
_EXPECTED = {
    ("hybrid", "selim school"): [(1, 1.0), (2, 0.583333), (3, 0.333333)],
    ("explain", "selim school"): [(1, 1.0), (2, 0.583333), (3, 0.333333)],
    ("dense", "selim school"): [(1, 0.666667), (3, 0.408248), (2, 0.316228)],
    ("hybrid", "lemon tree"): [(3, 0.833333), (5, 0.833333), (2, 0.25)],
    ("explain", "lemon tree"): [(3, 0.833333), (5, 0.833333), (2, 0.25)],
    ("dense", "lemon tree"): [(3, 0.57735), (5, 0.514496), (2, 0.223607)],
    ("hybrid", "camera speakers hiro"): [(4, 1.0), (5, 0.333333), (2, 0.25)],
    ("explain", "camera speakers hiro"): [(4, 1.0), (5, 0.333333), (2, 0.25)],
    ("dense", "camera speakers hiro"): [(4, 0.912871), (5, 0.420084), (2, 0.365148)],
}
_MODES = {"hybrid": {"hybrid": True}, "explain": {"hybrid": True, "explain": True}, "dense": {"hybrid": False}}


@pytest.fixture
def store(tmp_path: Path):
    dense = _HashDense()
    vector_store = KnowledgeVectorStore(tmp_path / "qdrant", dense)
    vector_store.upsert_document_vectors(
        "00000000-0000-0000-0000-000000000001",
        tmp_path / "doc.md",
        "Doc",
        "text/markdown",
        [{"text": text, "heading_path": None} for text in _CHUNKS],
        dense.embed_texts(_CHUNKS),
        [_hash_sparse(text) for text in _CHUNKS],
        {},
        [],
        "2026-01-01T00:00:00+00:00",
    )
    yield vector_store, dense
    vector_store.close()


@pytest.mark.parametrize(("mode", "query"), sorted(_EXPECTED))
def test_search_gives_the_same_hits_as_before_the_move(store, mode: str, query: str) -> None:
    vector_store, dense = store
    hits = vector_store.search_hybrid(
        dense.embed_texts([query])[0], _hash_sparse(query), top_k=3, **_MODES[mode]
    )
    assert [(hit.ord, round(hit.score, 6)) for hit in hits] == _EXPECTED[(mode, query)]
