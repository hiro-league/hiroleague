"""Searching with the core's models (llm/search.py): an app embeds (`ai.embed`), reranks (`ai.rerank`) and reads chat's
memory settings (`memory.settings`) through the core. Against a fake core: no model runs. The test app declares the uses
"embedding" and "reranking" (conftest.py)."""

import asyncio

import pytest
from hiro_channel_sdk import ExtensionRequestError

from hiro_extension_kit.errors import Invalid, Unavailable
from hiro_extension_kit.hiroleague import info_for
from hiro_extension_kit.llm import LLMError, search
from hiro_extension_kit.testing import FakeCore, FakeLink

EMBEDDED = {"vectors": [[0.1, 0.2], [0.3, 0.4]], "dimensions": 2, "model": "openai:text-embedding-3-small",
            "profile_id": "small", "profile_name": "Small", "ms": 12}
RERANKED = {"results": [{"index": 1, "score": 0.9}, {"index": 0, "score": None}], "model": "voyage:rerank-3",
            "profile_id": "voyage", "profile_name": "Voyage", "ms": 30}
SETTINGS = {"memory": {"enabled": True}, "graph": {"search_recipe": "cross_encoder"},
            "embedder": {"profile_id": "small", "model": "openai:text-embedding-3-small"},
            "reranker": {"profile_id": "voyage", "model": "voyage:rerank-3"}}


@pytest.fixture
def core(monkeypatch):
    fake = FakeCore()
    fake.answers["ai.embed"] = EMBEDDED
    fake.answers["ai.rerank"] = RERANKED
    fake.answers["memory.settings"] = SETTINGS
    monkeypatch.setattr(search, "link", FakeLink(fake))
    return fake


def test_the_app_declares_its_search_uses_to_the_core():
    info = info_for("http://test.hiro.local")
    assert [(u.id, u.name) for u in info.embed_uses] == [("embedding", "Embedding")]
    assert [(u.id, u.name) for u in info.rerank_uses] == [("reranking", "Reranking")]


def test_embedding_asks_with_the_apps_first_use_and_reads_the_vectors(core):
    out = asyncio.run(search.embed(["hello", "world"]))
    assert core.asked[-1] == ("ai.embed", {"texts": ["hello", "world"], "use": "embedding"})
    assert out.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert (out.dimensions, out.model, out.profile_id, out.profile_name) == (2, "openai:text-embedding-3-small", "small", "Small")


def test_a_profile_of_its_own_is_sent_without_the_default_use(core):
    asyncio.run(search.embed(["x"], profile="other"))
    assert core.asked[-1] == ("ai.embed", {"texts": ["x"], "profile": "other"})


def test_reranking_reads_the_order_best_first(core):
    out = asyncio.run(search.rerank("wife", ["a", "b"], top_n=2))
    assert core.asked[-1] == ("ai.rerank", {"query": "wife", "documents": ["a", "b"], "use": "reranking", "top_n": 2})
    assert [(r.index, r.score) for r in out.results] == [(1, 0.9), (0, None)]
    assert (out.model, out.profile_id) == ("voyage:rerank-3", "voyage")


def test_memory_settings_are_read_from_the_core(core):
    assert asyncio.run(search.memory_settings()) == SETTINGS
    assert core.asked[-1] == ("memory.settings", {})


def test_knowledge_settings_are_read_from_the_core(core):
    answer = {"knowledge": {"retrieval": {"top_k": 8}}, "embedder": {"profile_id": "e", "model": "m"},
              "reranker": {"profile_id": None, "model": None}, "sparse_model": "Qdrant/bm25"}
    core.answers["knowledge.settings"] = answer
    assert asyncio.run(search.knowledge_settings()) == answer
    assert core.asked[-1] == ("knowledge.settings", {})


@pytest.mark.parametrize(
    ("code", "error"),
    [("no_profile", Unavailable), ("invalid", Invalid), ("failed", LLMError), ("timeout", LLMError)],
)
def test_the_cores_refusals_become_the_errors_callers_handle(core, code, error):
    core.answers["ai.embed"] = ExtensionRequestError(code, "because")
    with pytest.raises(error):
        asyncio.run(search.embed(["x"]))


def test_without_the_core_nothing_is_asked(core):
    core.connected = False
    with pytest.raises(Unavailable, match="isn't connected to HiroLeague"):
        asyncio.run(search.rerank("q", ["d"]))
    assert core.asked == []


def test_an_answer_it_cant_read_is_an_llm_error(core):
    core.answers["ai.embed"] = {"vectors": "nope"}
    with pytest.raises(LLMError, match="can't be read"):
        asyncio.run(search.embed(["x"]))
