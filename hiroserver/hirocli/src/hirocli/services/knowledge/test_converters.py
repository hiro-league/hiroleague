from __future__ import annotations

import os

import pytest

from hirocli.services.knowledge.converters import default_file_concurrency_for_embedder
from hirocli.services.knowledge.embedding_backends import FastEmbedBackend


class FakeEmbedder:
    dimension = 8

    def embed_texts(self, texts):
        return [[0.1] * self.dimension for _ in texts]


@pytest.mark.parametrize(
    ("cpu_count", "expected"),
    [(1, 1), (2, 2), (4, 4), (8, 4), (16, 4)],
)
def test_default_file_concurrency_for_fastembed_respects_cpu_count(
    monkeypatch: pytest.MonkeyPatch,
    cpu_count: int,
    expected: int,
) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: cpu_count)
    embedder = FastEmbedBackend(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    assert default_file_concurrency_for_embedder(embedder) == expected


def test_default_file_concurrency_for_catalog_embedder() -> None:
    assert default_file_concurrency_for_embedder(FakeEmbedder()) == 8
