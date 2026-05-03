"""Curated LLM provider and model catalog loaded from bundled YAML.

Phase 1: read-only queries for setup, tools, and admin (later). Runtime model
factory will consume this data separately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

Hosting = Literal["cloud", "local"]
ModelKind = Literal["chat", "tts", "stt", "embedding", "image_gen"]


class TtsVoicePreset(BaseModel):
    """Built-in TTS voice id for a provider (API-native ``id`` string).

    Used for admin/API dropdowns; HiroCLI TTS providers pass ``id`` through to the vendor SDK.
    Optional editorial labels — omit ``display_name`` when it adds no value beyond ``id``.
    """

    id: str = Field(min_length=1)
    display_name: str | None = None
    description: str | None = None


class PricingBlock(BaseModel):
    """USD pricing hints; not live vendor quotes."""

    input_per_1m_tokens: float | None = None
    output_per_1m_tokens: float | None = None
    cached_input_per_1m_tokens: float | None = None
    per_character: float | None = None
    per_second: float | None = None
    per_image: float | None = None
    estimated_usd_per_1k_chars_speech: float | None = Field(
        default=None,
        description=(
            "TTS: curated rough USD per ~1k chars of input script including typical audio output tokens; approximate."
        ),
    )
    pricing_updated_at: str
    pricing_source: str | None = None


class Provider(BaseModel):
    id: str
    display_name: str
    hosting: Hosting
    credential_env_keys: list[str] = Field(default_factory=list)
    docs_url: str | None = None
    default_base_url: str | None = None
    # Phase 3c: editorial defaults per model kind for onboarding (kind -> canonical id).
    recommended_models: dict[str, str] | None = None
    # Curated preset voices for this vendor's integrated TTS APIs (same list for all catalog TTS models).
    tts_voices: list[TtsVoicePreset] = Field(default_factory=list)
    metadata_updated_at: str
    notes: str | None = None


class ModelSpec(BaseModel):
    id: str
    provider_id: str
    display_name: str
    model_kind: ModelKind
    model_class: str | None = None
    context_window: int | None = None
    modalities: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    pricing: PricingBlock | None = None
    deprecated_since: str | None = None
    replacement_id: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def id_matches_provider_prefix(self) -> ModelSpec:
        expected_prefix = f"{self.provider_id}:"
        if not self.id.startswith(expected_prefix):
            raise ValueError(
                f"model id {self.id!r} must start with provider prefix {expected_prefix!r}"
            )
        return self


class CatalogDocument(BaseModel):
    """Root catalog document loaded from ``catalog.yaml``."""

    catalog_version: str = Field(
        ...,
        description=(
            "Semantic version string for this catalog snapshot (PEP 440 style), "
            "e.g. 0.1.3 — not monotonic integers."
        ),
    )
    providers: list[Provider]
    models: list[ModelSpec]

    @field_validator("catalog_version", mode="before")
    @classmethod
    def catalog_version_trim(cls, value: Any) -> str:
        """Normalize catalog_version from YAML (quote dotted versions so they are strings, not floats)."""
        if value is None:
            raise ValueError("catalog_version is required")
        stripped = str(value).strip()
        if not stripped:
            raise ValueError("catalog_version must be a non-empty string")
        return stripped

    @model_validator(mode="after")
    def cross_reference_providers(self) -> CatalogDocument:
        pids = {p.id for p in self.providers}
        for m in self.models:
            if m.provider_id not in pids:
                raise ValueError(
                    f"model {m.id!r} references unknown provider_id {m.provider_id!r}"
                )
        for m in self.models:
            if m.replacement_id is not None:
                known = {x.id for x in self.models}
                if m.replacement_id not in known:
                    raise ValueError(
                        f"model {m.id!r} replacement_id {m.replacement_id!r} not in catalog"
                    )
        models_by_id = {m.id: m for m in self.models}
        for prov in self.providers:
            if not prov.recommended_models:
                continue
            for kind, mid in prov.recommended_models.items():
                if kind not in (
                    "chat",
                    "tts",
                    "stt",
                    "embedding",
                    "image_gen",
                ):
                    raise ValueError(
                        f"provider {prov.id!r} recommended_models has unknown kind {kind!r}"
                    )
                spec = models_by_id.get(mid)
                if spec is None:
                    raise ValueError(
                        f"provider {prov.id!r} recommended_models[{kind!r}] = {mid!r} "
                        "not found in catalog models"
                    )
                if spec.provider_id != prov.id:
                    raise ValueError(
                        f"provider {prov.id!r} recommended model {mid!r} belongs to "
                        f"provider {spec.provider_id!r}, not {prov.id!r}"
                    )
                if spec.model_kind != kind:
                    raise ValueError(
                        f"provider {prov.id!r} recommended_models[{kind!r}] points to "
                        f"{mid!r} but that model has model_kind {spec.model_kind!r}, not {kind!r}"
                    )
        return self


@dataclass(frozen=True)
class DeprecatedModelInfo:
    """A model id that is deprecated and optional replacement."""

    model_id: str
    deprecated_since: str
    replacement_id: str | None


@dataclass(frozen=True)
class ValidationResult:
    """Split of model ids against the catalog (Phase 1 — minimal buckets)."""

    known: list[str]
    unknown: list[str]
    deprecated: list[DeprecatedModelInfo]


class ModelCatalog:
    """In-memory view of catalog.yaml."""

    def __init__(self, doc: CatalogDocument) -> None:
        self._doc = doc
        self._providers_by_id: dict[str, Provider] = {p.id: p for p in doc.providers}
        self._models_by_id: dict[str, ModelSpec] = {m.id: m for m in doc.models}

    @property
    def catalog_version(self) -> str:
        return self._doc.catalog_version

    @classmethod
    def load_from_path(cls, path: Path) -> ModelCatalog:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(CatalogDocument.model_validate(raw))

    @classmethod
    def load_bundled(cls) -> ModelCatalog:
        """Load packaged ``catalog_data/catalog.yaml`` (works when installed as wheel).

        Root ``catalog_version`` lives only in this YAML — no parallel constant in code.
        """
        root = resources.files("hirocli.catalog_data")
        catalog = root.joinpath("catalog.yaml")
        text = catalog.read_text(encoding="utf-8")
        raw = yaml.safe_load(text)
        return cls(CatalogDocument.model_validate(raw))

    def get_provider(self, provider_id: str) -> Provider | None:
        return self._providers_by_id.get(provider_id)

    def list_providers(self, *, hosting: Hosting | None = None) -> list[Provider]:
        out = list(self._doc.providers)
        if hosting is not None:
            out = [p for p in out if p.hosting == hosting]
        return sorted(out, key=lambda p: p.id)

    def get_model(self, model_id: str) -> ModelSpec | None:
        return self._models_by_id.get(model_id)

    def list_models(
        self,
        *,
        provider_id: str | None = None,
        model_kind: ModelKind | str | None = None,
        model_class: str | None = None,
        hosting: Hosting | None = None,
    ) -> list[ModelSpec]:
        out: list[ModelSpec] = []
        for m in self._doc.models:
            if provider_id is not None and m.provider_id != provider_id:
                continue
            if model_kind is not None and m.model_kind != model_kind:
                continue
            if model_class is not None and m.model_class != model_class:
                continue
            if hosting is not None:
                prov = self._providers_by_id.get(m.provider_id)
                if prov is None or prov.hosting != hosting:
                    continue
            out.append(m)
        return sorted(out, key=lambda x: x.id)

    def list_credential_env_keys(self, *, provider_id: str | None = None) -> list[str]:
        """Sorted unique env var names declared by providers (for setup checks)."""
        keys: set[str] = set()
        for p in self.list_providers():
            if provider_id is not None and p.id != provider_id:
                continue
            keys.update(p.credential_env_keys)
        return sorted(keys)

    def validate_model_ids(self, model_ids: list[str]) -> ValidationResult:
        known: list[str] = []
        unknown: list[str] = []
        deprecated: list[DeprecatedModelInfo] = []
        seen: set[str] = set()
        for mid in model_ids:
            if mid in seen:
                continue
            seen.add(mid)
            spec = self._models_by_id.get(mid)
            if spec is None:
                unknown.append(mid)
                continue
            if spec.deprecated_since:
                deprecated.append(
                    DeprecatedModelInfo(
                        model_id=mid,
                        deprecated_since=spec.deprecated_since,
                        replacement_id=spec.replacement_id,
                    )
                )
            else:
                known.append(mid)
        return ValidationResult(
            known=sorted(known),
            unknown=sorted(unknown),
            deprecated=sorted(deprecated, key=lambda d: d.model_id),
        )

    def suggested_defaults(self, provider_id: str) -> dict[str, str]:
        """Return the provider's ``recommended_models`` map (kind -> canonical id).

        Empty dict if the provider is missing or has no recommendations.
        """
        prov = self._providers_by_id.get(provider_id)
        if prov is None or not prov.recommended_models:
            return {}
        return dict(prov.recommended_models)


@lru_cache(maxsize=1)
def get_model_catalog() -> ModelCatalog:
    """Singleton catalog loaded from the bundled YAML."""
    cat = ModelCatalog.load_bundled()
    logger.debug(
        "Loaded LLM catalog v%s (%s providers, %s models)",
        cat.catalog_version,
        len(cat.list_providers()),
        len(cat._doc.models),
    )
    return cat


def reload_model_catalog() -> ModelCatalog:
    """Reload bundled ``catalog.yaml`` from package data (clears the in-process LRU cache).

    Next ``get_model_catalog()`` loads a fresh ``ModelCatalog``. Used by admin
    ``POST /catalog/reload`` and ``hiro catalog reload``.

    Note: long-lived objects that read the catalog only at process startup (for
    example ``TTSService``) are not automatically rebuilt.
    """
    clear_model_catalog_cache()
    cat = get_model_catalog()
    logger.info(
        "Reloaded LLM catalog v%s (%s providers, %s models)",
        cat.catalog_version,
        len(cat.list_providers()),
        len(cat._doc.models),
    )
    return cat


def clear_model_catalog_cache() -> None:
    """Clear the catalog singleton so the next ``get_model_catalog()`` reloads YAML.

    Used by tests, ``reload_model_catalog()``, and admin/CLI reload flows.
    """
    get_model_catalog.cache_clear()
