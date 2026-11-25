"""ai.embed, ai.rerank and memory.settings end to end, over the real extension socket and the SDK's client.

An extension declares its embed and rerank uses when it pairs; it embeds and reranks on the profiles picked for
"eval:<use>" (a fake embedder and a fake reranker answer: nothing is paid or downloaded), reads chat's memory settings,
and a device can't call any of it.
"""

from __future__ import annotations

from hirocli.runtime.tests.approved import approve_every_app

import asyncio
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.documents import Document

from hiro_channel_sdk.constants import METHOD_AI_EMBED, METHOD_AI_RERANK, METHOD_KNOWLEDGE_SETTINGS, METHOD_MEMORY_SETTINGS
from hiro_channel_sdk.extension import (
    STATUS_CONNECTED,
    STATUS_NOT_PAIRED,
    ExtensionClient,
    ExtensionCredentials,
    ExtensionInfo,
    ExtensionRequestError,
    ExtensionSearchUse,
    build_request,
)
from hirocli.domain.config import Config
from hirocli.domain.extensions import list_paired_extensions, start_extension_pairing
from hirocli.domain.preferences import WorkspacePreferences
from hirocli.runtime.extension_manager import ExtensionManager
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.request_handler import CALLER_DEVICE, RequestHandler
from hirocli.runtime.search_for_extensions import SEARCH_REQUEST_HANDLERS
from hirocli.services import search_profiles

PREFS = {
    "embedding": {
        "profiles": {"small": {"label": "Small", "model": "openai:text-embedding-3-small"}},
        "uses": {"eval:embedding": "small"},
    },
    "rerank": {
        "profiles": {"voyage": {"label": "Voyage", "model": "voyage:rerank-3"}},
        "uses": {"eval:reranking": "voyage"},
    },
    "graph": {"embedder_profile": "small", "reranker": {"profile": "voyage", "min_relevance": 0.25}},
}


class _FakeEmbedder:
    dimension = 3

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class _FakeCompressor:
    """Orders the documents by how many query words each holds; scores are already in [0, 1]."""

    def compress_documents(self, docs: list[Document], query: str) -> list[Document]:
        words = set(query.lower().split())
        scored = sorted(docs, key=lambda d: -len(words & set(d.page_content.lower().split())))
        out = []
        for d in scored:
            hits = len(words & set(d.page_content.lower().split()))
            out.append(Document(page_content=d.page_content, metadata={**d.metadata, "relevance_score": hits / len(words)}))
        return out


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_for(predicate: Any, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.02)


class _Sink:
    async def __call__(self, msg: Any) -> None:
        del msg


def test_embed_rerank_and_memory_settings_answer_an_extension(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    embedder = _FakeEmbedder()
    built: list[tuple[str, str | None]] = []

    def fake_resolve_embedder(workspace_path: Path, model: str, **kw: Any) -> _FakeEmbedder:
        built.append(("embed", model))
        return embedder

    def fake_resolve_reranker(model: str, **kw: Any) -> tuple[_FakeCompressor, bool]:
        built.append(("rerank", kw.get("device")))
        return _FakeCompressor(), True

    monkeypatch.setattr("hirocli.services.knowledge.embedder.resolve_knowledge_embedder", fake_resolve_embedder)
    monkeypatch.setattr("hirocli.services.knowledge.reranker.resolve_reranker", fake_resolve_reranker)
    search_profiles.forget_built()

    async def scenario() -> None:
        workspace = tmp_path / "ws"
        port = _free_port()
        ctx = SimpleNamespace(
            workspace_path=workspace,
            workspace_name="test",
            config=Config(extension_host="127.0.0.1", extension_port=port),
            stop_event=asyncio.Event(),
            preferences=WorkspacePreferencesRuntime(workspace, initial=WorkspacePreferences.model_validate(PREFS)),
            extension_manager=None,
        )
        handler = RequestHandler(ctx)  # type: ignore[arg-type]
        for name, fn, callers in SEARCH_REQUEST_HANDLERS:
            handler.register(name, fn, callers=callers)
        manager = ExtensionManager(ctx, handler)  # type: ignore[arg-type]
        ctx.extension_manager = manager
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])
        info = ExtensionInfo(
            name="eval",
            embed_uses=[ExtensionSearchUse(id="embedding", name="Embedding")],
            rerank_uses=[ExtensionSearchUse(id="reranking", name="Reranking")],
        )
        client = ExtensionClient(f"ws://127.0.0.1:{port}", info, ExtensionCredentials(tmp_path / "eval"))
        running = asyncio.create_task(client.run())
        await _wait_for(lambda: client.status == STATUS_NOT_PAIRED)
        client.pair(start_extension_pairing(workspace, code_length=6, ttl_seconds=60).code)
        await _wait_for(lambda: client.status == STATUS_CONNECTED)
        approve_every_app(workspace)  # Permissions phase 8: not what this test is about

        # The declared uses are kept with the paired extension.
        [paired] = list_paired_extensions(workspace)
        assert paired.info["embed_uses"] == [{"id": "embedding", "name": "Embedding"}]
        assert paired.info["rerank_uses"] == [{"id": "reranking", "name": "Reranking"}]
        # The admin's Uses tab lists them with their picks.
        from hirocli.admin_svelte.routes.search import search_use_groups

        [group] = search_use_groups(workspace, ctx.preferences.current)
        assert group["extension"] == "eval"
        assert group["embedding"] == [
            {"key": "eval:embedding", "id": "embedding", "name": "Embedding", "profile_id": "small", "status": "ok"}
        ]
        assert [(u["key"], u["profile_id"]) for u in group["rerank"]] == [("eval:reranking", "voyage")]

        # ai.embed with the use's profile.
        out = await client.request(METHOD_AI_EMBED, {"use": "embedding", "texts": ["hi", "hello"]})
        assert out["vectors"] == [[2.0, 1.0, 0.0], [5.0, 1.0, 0.0]]
        assert (out["dimensions"], out["model"], out["profile_id"], out["profile_name"]) == (
            3, "openai:text-embedding-3-small", "small", "Small"
        )
        # The model is built once and kept.
        await client.request(METHOD_AI_EMBED, {"use": "embedding", "texts": ["again"]})
        assert built.count(("embed", "openai:text-embedding-3-small")) == 1

        # ai.rerank: best first, by index, top_n kept.
        ranked = await client.request(
            METHOD_AI_RERANK,
            {"use": "reranking", "query": "wife birthday", "documents": ["a cat", "her birthday", "wife birthday party"], "top_n": 2},
        )
        assert [r["index"] for r in ranked["results"]] == [2, 1]
        assert ranked["results"][0]["score"] == 1.0
        assert (ranked["profile_id"], ranked["model"]) == ("voyage", "voyage:rerank-3")

        # memory.settings: chat's memory settings as the core runs them.
        settings = await client.request(METHOD_MEMORY_SETTINGS, {})
        assert settings["embedder"] == {"profile_id": "small", "model": "openai:text-embedding-3-small"}
        assert settings["reranker"] == {"profile_id": "voyage", "model": "voyage:rerank-3"}
        assert settings["graph"]["reranker"]["min_relevance"] == 0.25
        assert "retrieval" in settings["memory"]

        # knowledge.settings: chat's knowledge-base settings, and the models it embeds and reranks with.
        knowledge = await client.request(METHOD_KNOWLEDGE_SETTINGS, {})
        assert set(knowledge) == {"knowledge", "embedder", "reranker", "sparse_model"}
        assert {"chunking", "retrieval", "answering", "rewrite"} <= set(knowledge["knowledge"])
        assert set(knowledge["embedder"]) == {"profile_id", "model"} and knowledge["sparse_model"] == "Qdrant/bm25"

        # Refusals: a use it doesn't declare (Permissions phase 8), no texts, a bad top_n, a profile that's gone.
        for method, params, code in (
            (METHOD_AI_EMBED, {"use": "other", "texts": ["x"]}, "invalid"),
            (METHOD_AI_EMBED, {"use": "embedding", "texts": []}, "invalid"),
            (METHOD_AI_EMBED, {"texts": ["x"]}, "invalid"),
            (METHOD_AI_RERANK, {"use": "reranking", "query": "q", "documents": ["d"], "top_n": 0}, "invalid"),
            (METHOD_AI_RERANK, {"profile": "gone", "query": "q", "documents": ["d"]}, "no_profile"),
        ):
            with pytest.raises(ExtensionRequestError) as err:
                await client.request(method, params)
            assert err.value.code == code, (method, params)

        # A device can't call them: they look unknown to it.
        for method in (METHOD_AI_EMBED, METHOD_AI_RERANK, METHOD_MEMORY_SETTINGS, METHOD_KNOWLEDGE_SETTINGS):
            msg = build_request(method, {}, sender_id="phone", direction="inbound")
            refused = await handler.handle(msg, emit_outbound=_Sink(), caller=CALLER_DEVICE)
            assert refused is not None and json.loads(refused.content[0].body)["error"]["code"] == "method_not_found"

        await client.stop()
        ctx.stop_event.set()
        await asyncio.wait_for(asyncio.gather(server, running, return_exceptions=True), timeout=5)

    asyncio.run(scenario())
    search_profiles.forget_built()
