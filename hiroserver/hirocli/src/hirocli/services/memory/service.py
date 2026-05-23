"""Mem0-backed long-term memory service."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from ...domain.memory import mem0_history_db_path
from ...domain.model_factory import catalog_embedding_dimensions
from .audit_log import build_add_audit, build_search_audit, log_memory_add, log_memory_search
from .usage_capture import (
    MemoryAddResult,
    MemoryUsage,
    MemoryUsageCallbackHandler,
    memory_usage_scope,
)

log = Logger.get("SVC.MEMORY")

# Bumped from ``hiro_memory`` when we moved ``character_id`` from a metadata
# field into mem0's ``agent_id`` entity scope. Old collections are orphaned
# by design (initial-development mode: no migration).
MEMORY_COLLECTION_NAME = "hiro_memory_v2"


def _mem0_user_id(user_id: int) -> str:
    return str(user_id)


def _entity_filters(user_id: int, character_id: str | None) -> dict[str, Any]:
    """Filters dict for mem0 search / get_all using native entity scoping.

    ``character_id`` rides on mem0's ``agent_id`` (the entity slot mem0
    reserves for "the personality talking to the user"). User scoping is
    always applied; character is added when supplied.
    """
    filters: dict[str, Any] = {"user_id": _mem0_user_id(user_id)}
    if character_id:
        filters["agent_id"] = character_id
    return filters


def _merge_metadata_filters(
    base: dict[str, Any],
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    """AND-merge caller-supplied metadata filters into the base filter dict.

    Extra keys with simple values become flat equality filters; nested
    operator dicts (``{"gte": ...}``) pass through to mem0's filter dialect.
    """
    if not extra:
        return base
    merged = dict(base)
    for key, value in extra.items():
        # Reserved entity slots stay as top-level keys; everything else is
        # treated as metadata equality / operator filters per mem0 v3 syntax.
        if key in ("user_id", "agent_id", "run_id"):
            merged[key] = value
        else:
            merged[key] = value
    return merged


class Mem0MemoryService:
    """Thin async wrapper around the synchronous Mem0 SDK."""

    def __init__(
        self,
        *,
        workspace_path: Path,
        llm_model: str,
        llm_tuning: Any | None = None,
        embedding_model: str,
        credential_store: Any | None = None,
        search_prefs: Any | None = None,
        reranker_prefs: Any | None = None,
    ) -> None:
        from mem0 import Memory

        self._workspace_path = Path(workspace_path)
        qdrant_path = self._workspace_path / "memory" / "qdrant"
        qdrant_path.mkdir(parents=True, exist_ok=True)
        # Pin mem0's SQLite history file to the workspace so ``clear_channel_messages``
        # can wipe the per-session ``messages`` buffer (last-k extraction context)
        # without touching mem0's default ``~/.mem0/history.db`` shared by all workspaces.
        history_db = mem0_history_db_path(self._workspace_path)
        history_db.parent.mkdir(parents=True, exist_ok=True)
        # Single handler instance shared across mem0 LLM calls. Per-operation
        # isolation is enforced by ``memory_usage_scope`` (ContextVar) rather
        # than per-handler instances.
        self._usage_handler = MemoryUsageCallbackHandler()
        self._chat_model_id = llm_model
        self._chat_provider_id = llm_model.split(":", 1)[0] if ":" in llm_model else ""
        llm = _mem0_model_config(
            self._workspace_path,
            llm_model,
            required_kind="chat",
            credential_store=credential_store,
            callbacks=[self._usage_handler],
            tuning=llm_tuning,
        )
        embedder = _mem0_model_config(
            self._workspace_path,
            embedding_model,
            required_kind="embedding",
            credential_store=credential_store,
        )
        _log_embedding_model_change(self._workspace_path, embedding_model)
        config: dict[str, Any] = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": MEMORY_COLLECTION_NAME,
                    "embedding_model_dims": catalog_embedding_dimensions(embedding_model),
                    "path": str(qdrant_path),
                    "on_disk": True,
                },
            },
            "llm": llm,
            "embedder": embedder,
            "history_db_path": str(history_db),
        }
        reranker_config = _reranker_config(reranker_prefs)
        if reranker_config is not None:
            config["reranker"] = reranker_config
        self._memory = Memory.from_config(config)
        self._op_lock = asyncio.Lock()

        # Search defaults from preferences (per-call args still override).
        self._search_top_k = int(getattr(search_prefs, "top_k", 8))
        self._search_threshold = float(getattr(search_prefs, "threshold", 0.1))
        self._search_rerank_default = bool(getattr(search_prefs, "rerank", False))
        self._reranker_enabled = bool(getattr(reranker_prefs, "enabled", False))

    async def close(self) -> None:
        async with self._op_lock:
            memory = self._memory
            self._memory = None
            await asyncio.to_thread(_close_mem0_memory, memory)

    async def add(
        self,
        content: str,
        *,
        user_id: int,
        run_id: str,
        character_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryAddResult:
        text = str(content or "").strip()
        if not text:
            return MemoryAddResult(usage=None, stored_count=0)
        mem0_user = _mem0_user_id(user_id)
        meta = dict(metadata or {})
        t0 = time.perf_counter()
        async with self._op_lock:
            memory = self._require_memory()
            # ``memory_usage_scope`` binds a ContextVar that the callback handler
            # reads on each LLM call inside ``memory.add``. ``asyncio.to_thread``
            # propagates the context via ``copy_context`` so the sync mem0
            # internals fire callbacks against this accumulator.
            with memory_usage_scope() as acc:
                raw = await asyncio.to_thread(
                    memory.add,
                    text,
                    user_id=mem0_user,
                    agent_id=character_id,
                    run_id=str(run_id),
                    metadata=meta,
                )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        # mem0 returns ``{"results": [...]}`` where each item represents one
        # ADD/UPDATE/DELETE event applied to the vector store. An empty list
        # means extraction yielded no new memories *or* mem0 swallowed an
        # internal parse error — we surface the count to the caller so the
        # ledger / event payload reflects reality instead of always claiming
        # one stored row per turn.
        stored_items = tuple(_stored_result_items(raw))
        stored_count = len(stored_items)
        usage: MemoryUsage | None = None
        if acc.call_count > 0:
            usage = MemoryUsage(
                provider=self._chat_provider_id,
                model=self._chat_model_id,
                input_tokens=acc.input_tokens,
                output_tokens=acc.output_tokens,
                cached_input_tokens=acc.cached_input_tokens,
                reasoning_tokens=acc.reasoning_tokens,
                call_count=acc.call_count,
            )
        result = MemoryAddResult(
            usage=usage,
            stored_count=stored_count,
            stored_items=stored_items,
        )
        log_memory_add(
            log,
            build_add_audit(
                user_id=user_id,
                character_id=character_id,
                run_id=str(run_id),
                content=text,
                metadata=meta,
                stored_count=stored_count,
                stored_items=stored_items,
                usage=usage,
                elapsed_ms=elapsed_ms,
            ),
            user_id=user_id,
            character_id=character_id,
            run_id=str(run_id),
        )
        return result

    async def search(
        self,
        query: str,
        *,
        user_id: int,
        character_id: str,
        limit: int | None = None,
        threshold: float | None = None,
        rerank: bool | None = None,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        text = str(query or "").strip()
        if not text:
            return []

        top_k = self._search_top_k if limit is None else int(limit)
        eff_threshold = self._search_threshold if threshold is None else float(threshold)
        # Don't pass rerank=True when no reranker is configured — mem0 would
        # silently ignore it; we warn once via the log instead.
        want_rerank = self._search_rerank_default if rerank is None else bool(rerank)
        eff_rerank = bool(want_rerank and self._reranker_enabled)
        if want_rerank and not self._reranker_enabled:
            log.debug(
                "memory.search rerank requested but reranker is disabled in preferences",
            )

        filters = _merge_metadata_filters(
            _entity_filters(user_id, character_id),
            metadata_filters,
        )

        t0 = time.perf_counter()
        async with self._op_lock:
            memory = self._require_memory()
            result = await asyncio.to_thread(
                memory.search,
                text,
                filters=filters,
                top_k=top_k,
                threshold=eff_threshold,
                rerank=eff_rerank,
            )
        hits = _normalize_memories(result)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log_memory_search(
            log,
            build_search_audit(
                query=text,
                user_id=user_id,
                character_id=character_id,
                top_k=top_k,
                threshold=eff_threshold,
                rerank_requested=want_rerank,
                rerank_applied=eff_rerank,
                reranker_enabled=self._reranker_enabled,
                filters=filters,
                results=hits,
                elapsed_ms=elapsed_ms,
            ),
            user_id=user_id,
            character_id=character_id,
        )
        return hits

    async def list_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = _entity_filters(user_id, character_id)
        async with self._op_lock:
            memory = self._require_memory()
            result = await asyncio.to_thread(memory.get_all, filters=filters)
        return _normalize_memories(result)

    async def clear_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> int:
        existing = await self.list_all(user_id=user_id, character_id=character_id)
        mem0_user = _mem0_user_id(user_id)
        async with self._op_lock:
            memory = self._require_memory()
            kwargs: dict[str, Any] = {"user_id": mem0_user}
            if character_id:
                kwargs["agent_id"] = character_id
            await asyncio.to_thread(memory.delete_all, **kwargs)
        return len(existing)

    async def delete(self, memory_id: str) -> None:
        mid = str(memory_id or "").strip()
        if not mid:
            raise ValueError("Memory id is required.")
        async with self._op_lock:
            memory = self._require_memory()
            await asyncio.to_thread(memory.delete, mid)

    def _require_memory(self) -> Any:
        if self._memory is None:
            raise RuntimeError("Memory service is closed.")
        return self._memory


def _reranker_config(reranker_prefs: Any | None) -> dict[str, Any] | None:
    """Build mem0's ``reranker`` block from preferences, or ``None`` if disabled.

    Only ``sentence_transformer`` is supported today — the local cross-encoder
    path avoids any external API dependency for reranking.
    """
    if reranker_prefs is None or not bool(getattr(reranker_prefs, "enabled", False)):
        return None
    model = str(getattr(reranker_prefs, "model", "") or "").strip()
    if not model:
        return None
    cfg: dict[str, Any] = {"model": model}
    device = getattr(reranker_prefs, "device", None)
    if device:
        cfg["device"] = str(device)
    batch_size = getattr(reranker_prefs, "batch_size", None)
    if batch_size:
        cfg["batch_size"] = int(batch_size)
    return {"provider": "sentence_transformer", "config": cfg}


def _stored_result_items(raw: Any) -> list[dict[str, Any]]:
    """Return ADD/UPDATE result items from a mem0 ``add()`` payload."""
    if isinstance(raw, dict):
        results = raw.get("results")
    else:
        results = raw
    if not isinstance(results, list):
        return []
    items: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            items.append({"memory": str(item)})
            continue
        event = item.get("event")
        if event in (None, "ADD", "UPDATE"):
            items.append(dict(item))
    return items


def _normalize_memories(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, dict):
        for key in ("results", "memories"):
            value = result.get(key)
            if isinstance(value, list):
                return [_memory_dict(item) for item in value]
        return [_memory_dict(result)]
    if isinstance(result, list):
        return [_memory_dict(item) for item in result]
    return [_memory_dict(result)]


def _memory_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    data = getattr(item, "model_dump", None)
    if callable(data):
        return dict(data())
    return {"memory": str(item)}


def _close_mem0_memory(memory: Any | None) -> None:
    if memory is None:
        return
    vector_store = getattr(memory, "vector_store", None)
    client = getattr(vector_store, "client", None)
    client_close = getattr(client, "close", None)
    if callable(client_close):
        client_close()
    memory_close = getattr(memory, "close", None)
    if callable(memory_close):
        memory_close()


def _mem0_model_config(
    workspace_path: Path,
    model_id: str,
    *,
    required_kind: str,
    credential_store: Any | None,
    callbacks: list[Any] | None = None,
    tuning: Any | None = None,
) -> dict[str, Any]:
    from hirocli.domain.credential_store import CredentialStore
    from hirocli.domain.model_catalog import get_model_catalog
    from hirocli.domain.workspace import workspace_id_for_path

    catalog = get_model_catalog()
    spec = catalog.get_model(model_id)
    if spec is None:
        raise ValueError(f"Unknown memory {required_kind} model: {model_id}")
    if not spec.supports_kind(required_kind):
        raise ValueError(
            f"Memory {required_kind} model {model_id} has wrong kind: {spec.model_kind}"
        )

    wid = workspace_id_for_path(workspace_path)
    store = credential_store
    if store is None and wid is not None:
        store = CredentialStore(workspace_path, wid)
    if store is None:
        raise ValueError("Workspace path is not registered; cannot resolve memory credentials")
    if not store.is_configured(spec.provider_id):
        raise ValueError(f"Provider {spec.provider_id!r} is not configured for memory model {model_id}")

    api_model = _mem0_api_model_id(spec.provider_id, model_id, required_kind)

    # Chat models always route through the langchain adapter so we get a
    # single, provider-agnostic callback path for usage capture.
    if required_kind == "chat":
        from hirocli.domain.model_factory import build_chat_model_from_tuning
        from hirocli.domain.preferences import ModelTuning

        effective_tuning = ModelTuning(
            temperature=float(getattr(tuning, "temperature", 0)),
            max_tokens=int(getattr(tuning, "max_tokens", 8192)),
            thinking=getattr(tuning, "thinking", "low"),
        )
        model = build_chat_model_from_tuning(
            model_id,
            workspace_path=workspace_path,
            tuning=effective_tuning,
            credential_store=store,
            callbacks=callbacks or [],
        )
        return {"provider": "langchain", "config": {"model": model}}

    # Embedding (Phase 2 will revisit usage capture here) — keep mem0-native
    # provider mapping so existing embedder behavior is unchanged.
    provider = _mem0_provider_id(spec.provider_id)
    config: dict[str, Any] = {"model": api_model}
    cred = store.get(spec.provider_id)
    if cred is not None and cred.api_key:
        config["api_key"] = cred.api_key
    if cred is not None and cred.base_url:
        if spec.provider_id == "ollama":
            config["ollama_base_url"] = cred.base_url
        elif spec.provider_id == "lm_studio":
            config["lmstudio_base_url"] = cred.base_url

    if spec.provider_id == "google":
        config["embedding_dims"] = catalog_embedding_dimensions(model_id)
    return {"provider": provider, "config": config}


def _mem0_provider_id(provider_id: str) -> str:
    return {
        "google": "gemini",
        "lm_studio": "lmstudio",
    }.get(provider_id, provider_id)


def _mem0_api_model_id(provider_id: str, model_id: str, required_kind: str) -> str:
    short = model_id.split(":", 1)[1]
    if provider_id == "google" and required_kind == "embedding":
        return f"models/{short}"
    return short


def _log_embedding_model_change(workspace_path: Path, embedding_model: str) -> None:
    memory_dir = workspace_path / "memory"
    marker = memory_dir / "embedding_model.txt"
    qdrant_path = memory_dir / "qdrant"
    existing = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    has_store = qdrant_path.exists() and any(qdrant_path.iterdir())
    if existing and existing != embedding_model and has_store:
        log.error(
            "Memory embedding model changed; existing Qdrant vectors may be incompatible",
            previous=existing,
            current=embedding_model,
            qdrant_path=str(qdrant_path),
        )
    if not existing:
        memory_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(embedding_model, encoding="utf-8")
