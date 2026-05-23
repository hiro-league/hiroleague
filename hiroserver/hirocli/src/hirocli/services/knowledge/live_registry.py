"""Live knowledge service registry and point counting helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from qdrant_client import QdrantClient

from hirocli.services.knowledge.catalog_store import CatalogStore
from hirocli.services.knowledge.constants import COLLECTION_NAME, DB_FILENAME, KNOWLEDGE_DIR, QDRANT_DIR
from hirocli.services.knowledge.runtime_owner import is_owner_token_alive

if TYPE_CHECKING:
    from hirocli.services.knowledge.service import KnowledgeService

_LIVE_SERVICES: dict[str, list[KnowledgeService]] = {}
_LIVE_OWNER_TOKENS: dict[str, set[str]] = {}


def register_live_service(service: KnowledgeService) -> None:
    key = str(service.workspace_path.resolve())
    _LIVE_SERVICES.setdefault(key, []).append(service)
    owner_token = getattr(service, "owner_token", None)
    if owner_token:
        _LIVE_OWNER_TOKENS.setdefault(key, set()).add(str(owner_token))


def unregister_live_service(service: KnowledgeService) -> None:
    key = str(service.workspace_path.resolve())
    services = _LIVE_SERVICES.get(key)
    if not services:
        return
    try:
        services.remove(service)
    except ValueError:
        pass
    if not services:
        _LIVE_SERVICES.pop(key, None)
    owner_token = getattr(service, "owner_token", None)
    if owner_token and key in _LIVE_OWNER_TOKENS:
        _LIVE_OWNER_TOKENS[key].discard(str(owner_token))
        if not _LIVE_OWNER_TOKENS[key]:
            _LIVE_OWNER_TOKENS.pop(key, None)


def has_live_knowledge_service(workspace_path: Path) -> bool:
    key = str(Path(workspace_path).resolve())
    return bool(_LIVE_SERVICES.get(key))


def live_owner_tokens(workspace_path: Path) -> set[str]:
    key = str(Path(workspace_path).resolve())
    return set(_LIVE_OWNER_TOKENS.get(key, set()))


def maybe_recover_abandoned_work(workspace_path: Path) -> None:
    """Recover stale running jobs unless another live owner still holds them."""
    resolved = Path(workspace_path).resolve()
    if has_live_knowledge_service(resolved):
        return
    db_path = resolved / KNOWLEDGE_DIR / DB_FILENAME
    if not db_path.exists():
        return
    catalog = CatalogStore(db_path)
    catalog.ensure_schema()
    catalog.recover_abandoned_work(live_tokens=live_owner_tokens(resolved))


def count_knowledge_points(workspace_path: Path) -> int:
    resolved = str(Path(workspace_path).resolve())
    services = _LIVE_SERVICES.get(resolved) or []
    for live in services:
        try:
            client = live.vector_store.qdrant
            if not client.collection_exists(COLLECTION_NAME):
                continue
            return int(client.count(COLLECTION_NAME, exact=True).count)
        except Exception:
            continue
    if services:
        db_path = Path(workspace_path) / KNOWLEDGE_DIR / DB_FILENAME
        return CatalogStore.sql_known_chunk_count(db_path)
    db_path = Path(workspace_path) / KNOWLEDGE_DIR / DB_FILENAME
    sql_count = CatalogStore.sql_known_chunk_count(db_path)
    qdrant_path = Path(workspace_path) / KNOWLEDGE_DIR / QDRANT_DIR
    if not qdrant_path.exists():
        return sql_count
    try:
        client = QdrantClient(path=str(qdrant_path), force_disable_check_same_thread=True)
        try:
            if not client.collection_exists(COLLECTION_NAME):
                return sql_count
            return max(sql_count, int(client.count(COLLECTION_NAME, exact=True).count))
        finally:
            client.close()
    except Exception:
        return sql_count
