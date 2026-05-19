"""Mem0-backed long-term memory service."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from hiro_commons.log import Logger

from ...domain.memory import mem0_history_db_path
from .usage_capture import (
    MemoryAddResult,
    MemoryUsage,
    MemoryUsageCallbackHandler,
    memory_usage_scope,
)

log = Logger.get("SVC.MEMORY")


def _mem0_user_id(user_id: int) -> str:
    return str(user_id)


def _character_metadata_filter(character_id: str) -> dict[str, Any]:
    return {"metadata": {"character_id": character_id}}


def _search_filters(user_id: int, character_id: str) -> dict[str, Any]:
    return {
        "AND": [
            {"user_id": _mem0_user_id(user_id)},
            {
                "OR": [
                    _character_metadata_filter(character_id),
                    {"metadata": {"shared": True}},
                ]
            },
        ]
    }


def _list_filters(user_id: int, character_id: str | None) -> dict[str, Any]:
    uid = _mem0_user_id(user_id)
    if character_id:
        return {
            "AND": [
                {"user_id": uid},
                _character_metadata_filter(character_id),
            ]
        }
    return {"user_id": uid}


def _matches_character(row: dict[str, Any], character_id: str | None) -> bool:
    if not character_id:
        return True
    meta = row.get("metadata")
    if isinstance(meta, dict):
        return meta.get("character_id") == character_id
    return False


class Mem0MemoryService:
    """Thin async wrapper around the synchronous Mem0 SDK."""

    def __init__(
        self,
        *,
        workspace_path: Path,
        llm_model: str,
        embedding_model: str,
        credential_store: Any | None = None,
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
                    "collection_name": "hiro_memory",
                    "embedding_model_dims": _embedding_dims(embedding_model),
                    "path": str(qdrant_path),
                    "on_disk": True,
                },
            },
            "llm": llm,
            "embedder": embedder,
            "history_db_path": str(history_db),
        }
        self._memory = Memory.from_config(config)
        self._op_lock = asyncio.Lock()

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
        meta = {**(metadata or {}), "character_id": character_id, "shared": False}
        mem0_user = _mem0_user_id(user_id)
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
                    run_id=str(run_id),
                    metadata=meta,
                )
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
        return MemoryAddResult(
            usage=usage,
            stored_count=stored_count,
            stored_items=stored_items,
        )

    async def search(
        self,
        query: str,
        *,
        user_id: int,
        character_id: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        text = str(query or "").strip()
        if not text:
            return []

        filters = _search_filters(user_id, character_id)
        mem0_user = _mem0_user_id(user_id)

        async with self._op_lock:
            memory = self._require_memory()
            result = await _to_thread_with_fallbacks(
                memory.search,
                (text,),
                [
                    {"filters": filters, "limit": limit},
                    {"filters": filters, "top_k": limit},
                    {"filters": {"user_id": mem0_user}, "limit": limit},
                    {"user_id": mem0_user, "limit": limit},
                ],
            )
        rows = _normalize_memories(result)
        return [row for row in rows if _matches_character(row, character_id)][:limit]

    async def list_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = _list_filters(user_id, character_id)
        mem0_user = _mem0_user_id(user_id)
        async with self._op_lock:
            memory = self._require_memory()
            result = await _to_thread_with_fallbacks(
                memory.get_all,
                (),
                [
                    {"filters": filters},
                    {"user_id": mem0_user},
                ],
            )
        rows = _normalize_memories(result)
        return [row for row in rows if _matches_character(row, character_id)]

    async def clear_all(
        self,
        *,
        user_id: int,
        character_id: str | None = None,
    ) -> int:
        existing = await self.list_all(user_id=user_id, character_id=character_id)
        filters = _list_filters(user_id, character_id)
        mem0_user = _mem0_user_id(user_id)
        async with self._op_lock:
            memory = self._require_memory()
            await _to_thread_with_fallbacks(
                memory.delete_all,
                (),
                [
                    {"filters": filters},
                    {"user_id": mem0_user},
                ],
            )
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


async def _to_thread_with_fallbacks(
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs_options: list[dict[str, Any]],
) -> Any:
    last_error: Exception | None = None
    for kwargs in kwargs_options:
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except (TypeError, ValueError) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return await asyncio.to_thread(fn, *args)


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
        return _chat_langchain_config(spec.provider_id, api_model, store, callbacks or [])

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
        config["embedding_dims"] = _embedding_dims(model_id)
    return {"provider": provider, "config": config}


def _chat_langchain_config(
    provider_id: str,
    api_model: str,
    store: Any,
    callbacks: list[Any],
) -> dict[str, Any]:
    """Build a mem0 ``provider="langchain"`` config for any chat provider.

    Routing every chat provider through a langchain ``BaseChatModel`` gives us
    a single point to attach callbacks. The callback handler reads
    ``usage_metadata`` from each completion, which langchain normalizes across
    OpenAI / Anthropic / Google / Ollama / OpenAI-compatible endpoints.
    """
    from langchain.chat_models import init_chat_model

    cred = store.get(provider_id)

    if provider_id == "openai":
        api_key = getattr(cred, "api_key", None)
        if not api_key:
            raise ValueError("OpenAI API key missing for memory LLM")
        # GPT-5 / o-series reasoning models reject ``max_tokens`` and ``temperature``.
        if _is_openai_reasoning(api_model):
            model = init_chat_model(
                api_model,
                model_provider="openai",
                api_key=api_key,
                max_completion_tokens=2000,
                callbacks=callbacks,
            )
        else:
            model = init_chat_model(
                api_model,
                model_provider="openai",
                api_key=api_key,
                temperature=0,
                max_tokens=2000,
                callbacks=callbacks,
            )
        return {"provider": "langchain", "config": {"model": model}}

    if provider_id == "anthropic":
        api_key = getattr(cred, "api_key", None)
        if not api_key:
            raise ValueError("Anthropic API key missing for memory LLM")
        model = init_chat_model(
            api_model,
            model_provider="anthropic",
            api_key=api_key,
            temperature=0,
            max_tokens=2000,
            callbacks=callbacks,
        )
        return {"provider": "langchain", "config": {"model": model}}

    if provider_id == "google":
        api_key = getattr(cred, "api_key", None)
        if not api_key:
            raise ValueError("Google API key missing for memory LLM")
        # Thinking models count thinking tokens against ``max_output_tokens``.
        # Memory extraction is a small structured-JSON task that does not need
        # deep reasoning — pin thinking low so the response budget covers the
        # actual JSON instead of being eaten by hidden chain-of-thought, which
        # was producing truncated payloads ("Expecting ',' delimiter" parse
        # errors) on Gemini 3 (default thinking_level="high").
        google_kwargs: dict[str, Any] = {}
        lower_model = api_model.lower()
        if lower_model.startswith("gemini-3"):
            google_kwargs["thinking_level"] = "low"
        elif lower_model.startswith("gemini-2.5"):
            google_kwargs["thinking_budget"] = 0
        model = init_chat_model(
            api_model,
            model_provider="google_genai",
            google_api_key=api_key,
            temperature=0,
            max_output_tokens=8192,
            callbacks=callbacks,
            **google_kwargs,
        )
        return {"provider": "langchain", "config": {"model": model}}

    if provider_id == "ollama":
        from langchain_ollama import ChatOllama

        base_url = getattr(cred, "base_url", None)
        if not base_url:
            raise ValueError("Ollama base_url missing for memory LLM")
        model = ChatOllama(
            model=api_model,
            base_url=base_url,
            temperature=0,
            num_predict=2000,
            callbacks=callbacks,
        )
        return {"provider": "langchain", "config": {"model": model}}

    if provider_id == "lm_studio":
        from langchain_openai import ChatOpenAI

        base_url = getattr(cred, "base_url", None)
        if not base_url:
            raise ValueError("LM Studio base_url missing for memory LLM")
        # LM Studio is OpenAI-API-compatible; route through ChatOpenAI so the
        # standard ``usage_metadata`` callback path applies. API key is a
        # placeholder — LM Studio ignores it but ChatOpenAI requires non-empty.
        model = ChatOpenAI(
            model=api_model,
            base_url=base_url,
            api_key="lm-studio",
            temperature=0,
            max_tokens=2000,
            callbacks=callbacks,
        )
        return {"provider": "langchain", "config": {"model": model}}

    raise ValueError(f"Memory chat provider {provider_id!r} is not supported.")


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


def _is_openai_reasoning(api_model: str) -> bool:
    """OpenAI reasoning models (GPT-5, o-series) reject ``max_tokens``/``temperature``."""
    lower = api_model.lower()
    return lower.startswith("gpt-5") or lower.startswith("o1") or lower.startswith("o3") or lower.startswith("o4")


def _embedding_dims(model_id: str) -> int:
    return {
        "openai:text-embedding-3-small": 1536,
        "google:gemini-embedding-001": 768,
        "ollama:nomic-embed-text": 512,
    }.get(model_id, 1536)


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
