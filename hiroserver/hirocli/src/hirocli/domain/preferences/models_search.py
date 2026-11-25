"""Embedding and reranker profiles, and the uses that point at them (``prefs.embedding``, ``prefs.rerank``).

The search counterparts of AI profiles (``models_ai.py``) and voice profiles (``models_voice.py``), so an
extension (EvalHiro) can ask the core for vectors (``ai.embed``) and for an order (``ai.rerank``) with the
same models Hiro's own memory and knowledge use:

- An **embedding profile** is a named embedding model: a catalog embedding model (``openai:…``,
  ``google:…``, ``ollama:…``) or a local one (``sentence-transformers/…``). Vectors are bound to the model
  that made them, so a graph or a collection keeps its embedder (``io.check_embedder_transition``).
- A **reranker profile** is a named reranking model, catalog (``voyage:…``, ``cohere:…``) or local
  (``local:…``), with where a local one runs (``device``). How many results to keep and the relevance
  floor stay with each search.

Hiro's own four uses are fields of their own (``embedding_profile_ref`` / ``rerank_profile_ref``):
``graph.embedder_profile``, ``knowledge.embedder_profile``, ``graph.reranker.profile`` and
``knowledge.retrieval.reranker.profile``. Extensions' uses are ``uses["<extension name>:<use id>"]``,
declared in ``ExtensionInfo.embed_uses`` / ``rerank_uses``.

``profiles`` and ``uses`` are edited by the Catalog's Profiles tab (``save_skip``: the Preferences page
never sends them). The model is checked for its form only, not against the catalog: a model the catalog
dropped keeps working while its provider still serves it, and the admin's picker flags it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

from .defaults import pref_field

SEARCH_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# No dots: a use key is one segment of a preferences PATCH path ("embedding.uses.eval:embedding").
# "<extension key>:<use id>"; a publisher's key has one dot (acme.weather:summary), domain/extension_keys.py
_USE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}(?:\.[A-Za-z0-9][A-Za-z0-9_-]{0,63})?:[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
# Local embedders are FastEmbed's sentence-transformers models (services/knowledge/embedder_registry.py).
LOCAL_EMBEDDER_PREFIX = "sentence-transformers/"
RERANK_DEVICES: tuple[str, ...] = ("cpu", "cuda")


def _clean_label(value: str, what: str) -> str:
    label = " ".join(value.split())
    if not label:
        raise ValueError(f"an {what} profile needs a name")
    return label


def _check_model_form(value: str, *, local_prefixes: tuple[str, ...]) -> str:
    model = value.strip()
    if model.startswith(local_prefixes):
        if len(model) <= max(len(p) for p in local_prefixes if model.startswith(p)):
            raise ValueError(f"model {model!r} names no model")
        return model
    provider, sep, name = model.partition(":")
    if not sep or not provider or not name.strip():
        raise ValueError(f"model must be provider:model or a local model, got {model!r}")
    return model


class EmbeddingProfile(BaseModel):
    """One embedding profile (module notes)."""

    label: str = Field(min_length=1, max_length=80, title="Name")
    # A catalog embedding model ("openai:text-embedding-3-small") or a local one ("sentence-transformers/…").
    model: str = Field(min_length=3, title="Model")

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return _clean_label(value, "embedding")

    @field_validator("model")
    @classmethod
    def _model(cls, value: str) -> str:
        return _check_model_form(value, local_prefixes=(LOCAL_EMBEDDER_PREFIX,))


class RerankProfile(BaseModel):
    """One reranker profile (module notes)."""

    label: str = Field(min_length=1, max_length=80, title="Name")
    # A catalog reranker ("voyage:rerank-2.5", "cohere:rerank-v5.0-fast") or a local one ("local:bge-reranker-base").
    model: str = Field(min_length=3, title="Model")
    # Local models only: "cpu", "cuda"; None = the best one found.
    device: str | None = Field(default=None, title="Device")

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return _clean_label(value, "reranker")

    @field_validator("model")
    @classmethod
    def _model(cls, value: str) -> str:
        # Local rerankers are "local:<name>", which is also provider:model in form.
        return _check_model_form(value, local_prefixes=())

    @field_validator("device")
    @classmethod
    def _device(cls, value: str | None) -> str | None:
        device = (value or "").strip().lower()
        if not device or device == "auto":
            return None
        if device not in RERANK_DEVICES:
            raise ValueError(f"device must be one of {', '.join(RERANK_DEVICES)} (or empty for the best one found)")
        return device


def _check_links(section: str, profiles: dict[str, BaseModel], uses: dict[str, str | None]) -> None:
    for pid in profiles:
        if not SEARCH_PROFILE_ID.match(pid):
            raise ValueError(
                f"{section} profile id {pid!r} must be lowercase letters, digits, '-' or '_' (1–64 characters)"
            )
    for key, pid in uses.items():
        if not _USE_KEY.match(key):
            raise ValueError(f"{section} use {key!r} must be '<extension>:<use id>'")
        if pid is not None and pid not in profiles:
            raise ValueError(f"{section} use {key!r} points at an unknown profile {pid!r}")


class EmbeddingPreferences(BaseModel):
    """``prefs.embedding``: the embedding profiles and which profile each extension's embedding use asks with."""

    profiles: dict[str, EmbeddingProfile] = pref_field(save_skip=True, default_factory=dict)
    # "<extension name>:<use id>" → profile id; None = declared, no profile picked yet.
    uses: dict[str, str | None] = pref_field(save_skip=True, default_factory=dict)

    @model_validator(mode="after")
    def _validate_links(self) -> "EmbeddingPreferences":
        _check_links("embedding", self.profiles, self.uses)  # type: ignore[arg-type]
        return self


class RerankPreferences(BaseModel):
    """``prefs.rerank``: the reranker profiles and which profile each extension's reranking use asks with."""

    profiles: dict[str, RerankProfile] = pref_field(save_skip=True, default_factory=dict)
    uses: dict[str, str | None] = pref_field(save_skip=True, default_factory=dict)

    @model_validator(mode="after")
    def _validate_links(self) -> "RerankPreferences":
        _check_links("rerank", self.profiles, self.uses)  # type: ignore[arg-type]
        return self


__all__ = [
    "EmbeddingPreferences",
    "EmbeddingProfile",
    "LOCAL_EMBEDDER_PREFIX",
    "RERANK_DEVICES",
    "RerankPreferences",
    "RerankProfile",
    "SEARCH_PROFILE_ID",
]
