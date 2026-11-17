"""Embedding and reranking with a profile, for extensions (``ai.embed``, ``ai.rerank``).

The same builders Hiro's own memory and knowledge use (``services/knowledge/embedder.py``, ``reranker.py``), so an
extension (EvalHiro) gets the vectors and the order chat gets from the same profile. Which profile: the one the
request names, else the one picked for ``"<extension>:<use>"`` (``prefs.embedding.uses`` / ``prefs.rerank.uses``).

A built model is kept per (workspace, model[, device]): a local model takes seconds to load, and the next request
reuses it. Building and running are synchronous (model inference, network): callers run them off the event loop.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from ..domain.credential_store import CredentialStore
from ..domain.preferences import EmbeddingProfile, RerankProfile, WorkspacePreferences
from ..domain.workspace import workspace_id_for_path

MAX_TEXTS = 256  # texts one ai.embed carries
MAX_DOCUMENTS = 1000  # documents one ai.rerank orders
MAX_CHARS = 32_000  # characters in one text, query or document


class SearchError(Exception):
    """A refused or failed request: ``code`` is the contract's (``no_profile``, ``invalid``, ``failed``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Embedded:
    vectors: list[list[float]]
    dimensions: int
    model: str
    profile_id: str
    profile_name: str
    ms: int


@dataclass(frozen=True)
class Reranked:
    results: list[dict[str, Any]]  # [{index, score}], best first
    model: str
    profile_id: str
    profile_name: str
    ms: int


_lock = threading.Lock()
_embedders: dict[tuple[str, str], Any] = {}
_rerankers: dict[tuple[str, str, str], tuple[Any, bool]] = {}


def pick_embedding(
    prefs: WorkspacePreferences, *, use_key: str | None, profile_id: str | None
) -> tuple[str, EmbeddingProfile]:
    pid = (profile_id or "").strip() or (prefs.embedding.uses.get(use_key) if use_key else None)
    if not pid:
        raise SearchError("no_profile", f"No embedding profile for {use_key!r}: pick one on the Catalog's Profiles → Uses tab.")
    profile = prefs.embedding.profiles.get(pid)
    if profile is None:
        raise SearchError("no_profile", f"There's no embedding profile {pid!r}.")
    return pid, profile


def pick_rerank(
    prefs: WorkspacePreferences, *, use_key: str | None, profile_id: str | None
) -> tuple[str, RerankProfile]:
    pid = (profile_id or "").strip() or (prefs.rerank.uses.get(use_key) if use_key else None)
    if not pid:
        raise SearchError("no_profile", f"No reranker profile for {use_key!r}: pick one on the Catalog's Profiles → Uses tab.")
    profile = prefs.rerank.profiles.get(pid)
    if profile is None:
        raise SearchError("no_profile", f"There's no reranker profile {pid!r}.")
    return pid, profile


def _store(workspace_path: Path) -> CredentialStore | None:
    wid = workspace_id_for_path(workspace_path)
    return CredentialStore(workspace_path, wid) if wid is not None else None


def _embedder(workspace_path: Path, model: str) -> Any:
    key = (str(workspace_path), model)
    with _lock:
        backend = _embedders.get(key)
    if backend is not None:
        return backend
    from .knowledge.embedder import UnconfiguredEmbedder, resolve_knowledge_embedder

    try:
        backend = resolve_knowledge_embedder(workspace_path, model, credential_store=_store(workspace_path))
    except ValueError as exc:
        raise SearchError("failed", str(exc)) from exc
    if isinstance(backend, UnconfiguredEmbedder):
        raise SearchError("failed", backend.reason)
    with _lock:
        _embedders[key] = backend
    return backend


def embed(workspace_path: Path, pid: str, profile: EmbeddingProfile, texts: list[str]) -> Embedded:
    """Vectors for ``texts`` with the profile's model (synchronous)."""
    started = time.monotonic()
    backend = _embedder(workspace_path, profile.model)
    try:
        vectors = backend.embed_texts(texts)
    except Exception as exc:  # the provider or the local model failed: say why
        raise SearchError("failed", f"{profile.model} couldn't embed: {exc}") from exc
    vectors = [[float(x) for x in v] for v in vectors]
    return Embedded(
        vectors=vectors,
        dimensions=len(vectors[0]) if vectors else int(getattr(backend, "dimension", 0) or 0),
        model=profile.model,
        profile_id=pid,
        profile_name=profile.label,
        ms=int((time.monotonic() - started) * 1000),
    )


def _reranker(workspace_path: Path, profile: RerankProfile) -> tuple[Any, bool]:
    key = (str(workspace_path), profile.model, profile.device or "")
    with _lock:
        built = _rerankers.get(key)
    if built is None:
        from .knowledge.reranker import resolve_reranker

        try:
            built = resolve_reranker(
                profile.model,
                workspace_path=workspace_path,
                top_n=MAX_DOCUMENTS,  # order every document; top_n is cut here
                device=profile.device,
                credential_store=_store(workspace_path),
            )
        except Exception as exc:  # unknown model, no key, a local model not downloaded
            raise SearchError("failed", f"{profile.model} can't rerank here: {exc}") from exc
        with _lock:
            _rerankers[key] = built
    return built


def rerank(
    workspace_path: Path, pid: str, profile: RerankProfile, query: str, documents: list[str], top_n: int | None
) -> Reranked:
    """``documents`` in order of relevance to ``query`` with the profile's model (synchronous)."""
    from .knowledge.reranker import _normalize

    started = time.monotonic()
    compressor, calibrated = _reranker(workspace_path, profile)
    docs = [Document(page_content=text, metadata={"_idx": i}) for i, text in enumerate(documents)]
    try:
        ordered = compressor.compress_documents(docs, query) if docs else []
    except Exception as exc:
        raise SearchError("failed", f"{profile.model} couldn't rerank: {exc}") from exc
    results: list[dict[str, Any]] = []
    for doc in ordered:
        idx = doc.metadata.get("_idx")
        if not isinstance(idx, int) or not (0 <= idx < len(documents)):
            continue
        raw = doc.metadata.get("relevance_score")
        score = _normalize(float(raw), calibrated=calibrated) if raw is not None else None
        results.append({"index": idx, "score": score})
    if top_n:
        results = results[:top_n]
    return Reranked(
        results=results,
        model=profile.model,
        profile_id=pid,
        profile_name=profile.label,
        ms=int((time.monotonic() - started) * 1000),
    )


def forget_built() -> None:
    """Drop every kept model (tests; a provider key changed)."""
    with _lock:
        _embedders.clear()
        _rerankers.clear()


__all__ = [
    "Embedded",
    "MAX_CHARS",
    "MAX_DOCUMENTS",
    "MAX_TEXTS",
    "Reranked",
    "SearchError",
    "embed",
    "forget_built",
    "pick_embedding",
    "pick_rerank",
    "rerank",
]
