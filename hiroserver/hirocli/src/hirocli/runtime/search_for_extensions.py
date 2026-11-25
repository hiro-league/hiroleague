"""The core searches for extensions — the ``ai.embed``, ``ai.rerank`` and ``memory.settings`` requests.

An extension (EvalHiro) asks for vectors and for an order with the same models Hiro's memory uses, instead of keeping
its own: ``ai.embed`` / ``ai.rerank`` name one of the extension's declared uses (``ExtensionInfo.embed_uses`` /
``rerank_uses``), and the core uses the profile picked for ``"<extension>:<use>"`` (or the profile the request names).
``memory.settings`` answers chat's memory settings as the core runs them, so a test of memory runs as chat does.

Like ``ai.ask``, the core doesn't check that the use was declared (a known gap, hiro-docs design.md §9). Extensions
only. Errors answer the contract's codes (``no_profile``, ``invalid``, ``failed``) through ``RequestRefused``.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from hiro_channel_sdk.constants import (
    AI_ERROR_FAILED,
    AI_ERROR_INVALID,
    METHOD_AI_EMBED,
    METHOD_AI_RERANK,
    METHOD_KNOWLEDGE_SETTINGS,
    METHOD_MEMORY_SETTINGS,
)
from hiro_memory.knowledge.constants import DEFAULT_SPARSE_MODEL
from hiro_commons.log import Logger

from ..domain.preferences import (
    resolve_graph_reranker_profile,
    resolve_graphiti_embedder_model,
    resolve_knowledge_embedder_model,
    resolve_knowledge_reranker_profile,
)
from ..services import fakes
from ..services import search_profiles as search
from .ai_for_extensions import _caller_name, refuse_undeclared
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused, gate

log = Logger.get("AI.SEARCH")


def _text(params: dict[str, Any], key: str, *, required: bool) -> str:
    value = params.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise RequestRefused(AI_ERROR_INVALID, f"{key} is required (text).")
    if len(value) > search.MAX_CHARS:
        raise RequestRefused(AI_ERROR_INVALID, f"{key} is too long: {len(value)} characters, the limit is {search.MAX_CHARS}.")
    return value


def _texts(params: dict[str, Any], key: str, limit: int) -> list[str]:
    value = params.get(key)
    if not isinstance(value, list) or not value:
        raise RequestRefused(AI_ERROR_INVALID, f"{key} is required (a list of texts).")
    if len(value) > limit:
        raise RequestRefused(AI_ERROR_INVALID, f"Too many {key}: {len(value)}, the limit is {limit}.")
    for i, text in enumerate(value):
        if not isinstance(text, str):
            raise RequestRefused(AI_ERROR_INVALID, f"{key}[{i}] must be text.")
        if len(text) > search.MAX_CHARS:
            raise RequestRefused(AI_ERROR_INVALID, f"{key}[{i}] is too long: the limit is {search.MAX_CHARS} characters.")
    return value


def _use_and_profile(params: dict[str, Any], name: str) -> tuple[str | None, str]:
    use = _text(params, "use", required=False).strip()
    profile = _text(params, "profile", required=False).strip()
    if not use and not profile:
        raise RequestRefused(AI_ERROR_INVALID, "use or profile is required.")
    return (f"{name}:{use}" if use else None), profile


async def handle_ai_embed(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    # embeddings and reranking are AI: a test environment's switchboard decides
    mode = gate("ai", AI_ERROR_FAILED, fakes=True)
    name = await _caller_name(ctx)
    use_key, profile_id = _use_and_profile(params, name)
    await refuse_undeclared(ctx, name, "embed_uses", _text(params, "use", required=False).strip())  # phase 8
    texts = _texts(params, "texts", search.MAX_TEXTS)
    if mode == "fake":
        # The stand-in (services/fakes.py): each text's own repeatable vector, sized as the picked profile's model
        # makes them, so it fits an index that model filled. No profile picked: the default size.
        picked = ctx.server_ctx.preferences.current.embedding
        pid = profile_id or (picked.uses.get(use_key) if use_key else None) or ""
        model = picked.profiles[pid].model if pid in picked.profiles else ""
        dims = fakes.dims_of(model)
        log.info(f"✅ Embedded by the stand-in — {name} · {use_key or 'own pick'}", texts=len(texts), dimensions=dims)
        return asdict(search.Embedded([fakes.vector(t, dims) for t in texts], dims, fakes.MODEL, fakes.PROVIDER,
                                      fakes.PROFILE_NAME, 0))
    try:
        pid, profile = search.pick_embedding(ctx.server_ctx.preferences.current, use_key=use_key, profile_id=profile_id)
        out = await asyncio.to_thread(search.embed, ctx.workspace_path, pid, profile, texts)
    except search.SearchError as exc:
        log.warning(f"⚠️ Not embedded — {name} · {use_key or profile_id}", error=exc.message)
        raise RequestRefused(exc.code, exc.message) from exc
    log.info(f"✅ Embedded — {name} · {use_key or 'own pick'} · {profile.label}", texts=len(texts), elapsed_ms=out.ms)
    return asdict(out)


async def handle_ai_rerank(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    mode = gate("ai", AI_ERROR_FAILED, fakes=True)
    name = await _caller_name(ctx)
    use_key, profile_id = _use_and_profile(params, name)
    await refuse_undeclared(ctx, name, "rerank_uses", _text(params, "use", required=False).strip())  # phase 8
    query = _text(params, "query", required=True)
    documents = _texts(params, "documents", search.MAX_DOCUMENTS)
    top_n = params.get("top_n")
    if top_n is not None and (not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1):
        raise RequestRefused(AI_ERROR_INVALID, "top_n must be a whole number of 1 or more.")
    if mode == "fake":  # the stand-in: by the words each document shares with the query
        log.info(f"✅ Reranked by the stand-in — {name} · {use_key or 'own pick'}", documents=len(documents))
        return asdict(search.Reranked(fakes.ranked(query, documents, top_n), fakes.MODEL, fakes.PROVIDER,
                                      fakes.PROFILE_NAME, 0))
    try:
        pid, profile = search.pick_rerank(ctx.server_ctx.preferences.current, use_key=use_key, profile_id=profile_id)
        out = await asyncio.to_thread(search.rerank, ctx.workspace_path, pid, profile, query, documents, top_n)
    except search.SearchError as exc:
        log.warning(f"⚠️ Not reranked — {name} · {use_key or profile_id}", error=exc.message)
        raise RequestRefused(exc.code, exc.message) from exc
    log.info(f"✅ Reranked — {name} · {use_key or 'own pick'} · {profile.label}", documents=len(documents), elapsed_ms=out.ms)
    return asdict(out)


async def handle_memory_settings(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    del params
    await _caller_name(ctx)
    prefs = ctx.server_ctx.preferences.current
    graph = prefs.graph.model_dump(mode="json")
    reranker = resolve_graph_reranker_profile(prefs)
    return {
        "memory": prefs.memory.model_dump(mode="json"),
        "graph": graph,
        "embedder": {"profile_id": prefs.graph.embedder_profile, "model": resolve_graphiti_embedder_model(prefs)},
        "reranker": {
            "profile_id": prefs.graph.reranker.profile,
            "model": reranker.model if reranker is not None else None,
        },
    }


async def handle_knowledge_settings(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Chat's knowledge-base settings, read only (EvalHiro's knowledge eval runs the knowledge base as chat does)."""
    del params
    await _caller_name(ctx)
    prefs = ctx.server_ctx.preferences.current
    reranker = resolve_knowledge_reranker_profile(prefs)
    return {
        "knowledge": prefs.knowledge.model_dump(mode="json"),
        "embedder": {"profile_id": prefs.knowledge.embedder_profile, "model": resolve_knowledge_embedder_model(prefs)},
        "reranker": {
            "profile_id": prefs.knowledge.retrieval.reranker.profile,
            "model": reranker.model if reranker is not None else None,
        },
        "sparse_model": DEFAULT_SPARSE_MODEL,
    }


SEARCH_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_AI_EMBED, handle_ai_embed, EXTENSIONS_ONLY),
    (METHOD_AI_RERANK, handle_ai_rerank, EXTENSIONS_ONLY),
    (METHOD_MEMORY_SETTINGS, handle_memory_settings, EXTENSIONS_ONLY),
    (METHOD_KNOWLEDGE_SETTINGS, handle_knowledge_settings, EXTENSIONS_ONLY),
)
