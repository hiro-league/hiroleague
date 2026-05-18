"""Mem0-backed long-term memory service."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from hiro_commons.log import Logger

log = Logger.get("SVC.MEMORY")


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
        llm = _mem0_model_config(
            self._workspace_path,
            llm_model,
            required_kind="chat",
            credential_store=credential_store,
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
        }
        self._memory = Memory.from_config(config)

    async def add(
        self,
        content: str,
        *,
        user_id: str,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        text = str(content or "").strip()
        if not text:
            return
        meta = {**(metadata or {}), "agent_id": agent_id, "shared": False}
        await asyncio.to_thread(
            self._memory.add,
            text,
            user_id=user_id,
            agent_id=agent_id,
            metadata=meta,
        )

    async def search(
        self,
        query: str,
        *,
        user_id: str,
        agent_id: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        text = str(query or "").strip()
        if not text:
            return []

        filters = {
            "AND": [
                {"user_id": user_id},
                {"OR": [{"agent_id": agent_id}, {"metadata": {"shared": True}}]},
            ]
        }

        result = await _to_thread_with_fallbacks(
            self._memory.search,
            (text,),
            [
                {"filters": filters, "limit": limit},
                {"filters": filters, "top_k": limit},
                {"filters": {"user_id": user_id, "agent_id": agent_id}, "limit": limit},
                {"user_id": user_id, "agent_id": agent_id, "limit": limit},
            ],
        )
        return _normalize_memories(result)[:limit]

    async def list_all(
        self,
        *,
        user_id: str,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"user_id": user_id}
        if agent_id:
            filters["agent_id"] = agent_id
        result = await _to_thread_with_fallbacks(
            self._memory.get_all,
            (),
            [
                {"filters": filters},
                {"user_id": user_id, **({"agent_id": agent_id} if agent_id else {})},
            ],
        )
        return _normalize_memories(result)

    async def clear_all(
        self,
        *,
        user_id: str,
        agent_id: str | None = None,
    ) -> int:
        existing = await self.list_all(user_id=user_id, agent_id=agent_id)
        filters: dict[str, Any] = {"user_id": user_id}
        if agent_id:
            filters["agent_id"] = agent_id
        await _to_thread_with_fallbacks(
            self._memory.delete_all,
            (),
            [
                {"filters": filters},
                {"user_id": user_id, **({"agent_id": agent_id} if agent_id else {})},
            ],
        )
        return len(existing)


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


def _mem0_model_config(
    workspace_path: Path,
    model_id: str,
    *,
    required_kind: str,
    credential_store: Any | None,
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

    provider = _mem0_provider_id(spec.provider_id)
    api_model = _mem0_api_model_id(spec.provider_id, model_id, required_kind)
    if required_kind == "chat" and spec.provider_id == "openai" and _is_openai_gpt5(api_model):
        return _openai_gpt5_langchain_config(api_model, store.get(spec.provider_id))

    config: dict[str, Any] = {"model": api_model}
    cred = store.get(spec.provider_id)
    if cred is not None and cred.api_key:
        config["api_key"] = cred.api_key
    if cred is not None and cred.base_url:
        if spec.provider_id == "ollama":
            config["ollama_base_url"] = cred.base_url
        elif spec.provider_id == "lm_studio":
            config["lmstudio_base_url"] = cred.base_url

    if required_kind == "embedding" and spec.provider_id == "google":
        config["embedding_dims"] = _embedding_dims(model_id)
    return {"provider": provider, "config": config}


def _openai_gpt5_langchain_config(api_model: str, cred: Any | None) -> dict[str, Any]:
    """Use Mem0's LangChain adapter so OpenAI GPT-5 uses max_completion_tokens."""
    from langchain.chat_models import init_chat_model

    api_key = getattr(cred, "api_key", None) if cred is not None else None
    if not api_key:
        raise ValueError("OpenAI API key missing for memory LLM")
    model = init_chat_model(
        api_model,
        model_provider="openai",
        api_key=api_key,
        max_completion_tokens=2000,
    )
    return {"provider": "langchain", "config": {"model": model}}


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


def _is_openai_gpt5(api_model: str) -> bool:
    return api_model.lower().startswith("gpt-5")


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
