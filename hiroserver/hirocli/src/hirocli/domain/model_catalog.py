"""Curated LLM provider and model catalog loaded from bundled YAML.

Phase 1: read-only queries for setup, tools, and admin (later). Runtime model
factory will consume this data separately.
"""

from __future__ import annotations

import logging
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

Hosting = Literal["cloud", "local"]
ModelKind = Literal["chat", "tts", "stt", "embedding", "image_gen", "rerank"]
# Single source of truth for valid kinds — derived from the Literal so adding a new kind
# (e.g. "rerank") only requires editing ModelKind. Validators and Tool allowlists use this.
MODEL_KINDS: tuple[ModelKind, ...] = get_args(ModelKind)


class TtsVoicePreset(BaseModel):
    """Built-in TTS voice id for a provider (API-native ``id`` string).

    Used for admin/API dropdowns; HiroCLI TTS providers pass ``id`` through to the vendor SDK.
    Optional editorial labels — omit ``display_name`` when it adds no value beyond ``id``.
    """

    id: str = Field(min_length=1)
    display_name: str | None = None
    description: str | None = None


class ProviderFreeOffer(BaseModel):
    """Editorial note about a vendor free tier, trial, or promotional allowance."""

    label: str = Field(min_length=1, description="Short badge text, e.g. 'Free rerank'.")
    summary: str = Field(
        min_length=1,
        description="One-line tooltip on the admin free-offer icon.",
    )
    updated_at: str = Field(
        description="ISO YYYY-MM-DD when this offer note was last verified against vendor docs.",
    )
    details: str | None = Field(
        default=None,
        description=(
            "Optional longer plain-text for the admin dialog; YAML line wraps are folded on display."
        ),
    )
    details_url: str | None = Field(
        default=None,
        description="Optional link to vendor pricing or trial documentation.",
    )


class PricingBlock(BaseModel):
    """USD pricing hints; not live vendor quotes."""

    input_per_1m_tokens: float | None = None
    output_per_1m_tokens: float | None = None
    cached_input_per_1m_tokens: float | None = None
    audio_input_per_1m_tokens: float | None = Field(
        default=None,
        description=(
            "STT: USD per 1M audio-input tokens — distinct from the text input rate for dual-use "
            "chat models used as STT. STT-only models leave this null (their input_per_1m is audio)."
        ),
    )
    per_character: float | None = None
    per_second: float | None = None
    per_image: float | None = None
    per_step: float | None = Field(
        default=None,
        description=(
            "Image gen (diffusion): USD per inference step. Pairs with per_image, which then "
            "carries the fixed per-image component (e.g. Cloudflare's resolution-tile charge)."
        ),
    )
    estimated_usd_per_1k_chars_speech: float | None = Field(
        default=None,
        description=(
            "TTS: curated rough USD per ~1k chars of input script including typical audio output tokens; approximate."
        ),
    )
    estimated_usd_per_1k_searches: float | None = Field(
        default=None,
        description=(
            "Rerank (Cohere-style): USD per 1,000 search units (1 query + up to 100 docs); approximate."
        ),
    )
    per_1k_tokens: float | None = Field(
        default=None,
        description=(
            "Rerank (Voyage-style): USD per 1K processed tokens "
            "(query×docs + sum(doc tokens)); pairs with input_per_1m_tokens × 1000."
        ),
    )
    estimated_usd_per_request: float | None = Field(
        default=None,
        description=(
            "Rerank (Voyage-style): vendor table estimate per request "
            "(100 docs; query + each doc sum to 500 tokens); approximate."
        ),
    )
    pricing_updated_at: str
    pricing_source: str | None = None


class Provider(BaseModel):
    id: str
    display_name: str
    hosting: Hosting
    credential_env_keys: list[str] = Field(default_factory=list)
    # Cloudflare-style vendors need a non-secret account identifier in addition to the API
    # token (it is part of the REST URL). When true, provider-add surfaces require account_id.
    requires_account_id: bool = False
    # Env var names that may carry the account identifier (setup / scan-env fallback).
    account_env_keys: list[str] = Field(default_factory=list)
    docs_url: str | None = None
    default_base_url: str | None = None
    # Phase 3c: editorial defaults per model kind for onboarding (kind -> canonical id).
    recommended_models: dict[str, str] | None = None
    # Curated preset voices for this vendor's integrated TTS APIs (same list for all catalog TTS models).
    tts_voices: list[TtsVoicePreset] = Field(default_factory=list)
    # Editorial free-tier / trial notes surfaced in admin provider tables.
    free_offers: list[ProviderFreeOffer] = Field(default_factory=list)
    metadata_updated_at: str
    notes: str | None = None


class ModelSpec(BaseModel):
    id: str
    provider_id: str
    display_name: str
    model_kind: ModelKind = Field(
        description="Primary/editorial kind — UI badges and pricing tables use this first."
    )
    extra_kinds: list[ModelKind] = Field(
        default_factory=list,
        description=(
            "Additional Hiro purposes this row is valid for (e.g. chat model also usable as STT). "
            "Must not repeat model_kind; see supports_kind()."
        ),
    )
    model_class: str | None = None
    context_window: int | None = None
    modalities: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    pricing: PricingBlock | None = None
    released_at: str | None = Field(
        default=None,
        description="Vendor model/API launch date (ISO YYYY-MM-DD); editorial, verify against release notes.",
    )
    deprecated_since: str | None = None
    replacement_id: str | None = None
    notes: str | None = None

    def supports_kind(self, kind: ModelKind | str) -> bool:
        """True if this catalog row may be selected for ``kind`` (primary or extra)."""
        k = str(kind)
        if self.model_kind == k:
            return True
        return k in self.extra_kinds

    def supports_reasoning(self) -> bool:
        """True when workspace thinking/reasoning tuning applies to this model."""
        return "reasoning" in self.features

    @model_validator(mode="after")
    def id_matches_provider_prefix(self) -> ModelSpec:
        expected_prefix = f"{self.provider_id}:"
        if not self.id.startswith(expected_prefix):
            raise ValueError(
                f"model id {self.id!r} must start with provider prefix {expected_prefix!r}"
            )
        return self

    @model_validator(mode="after")
    def extra_kinds_consistent(self) -> ModelSpec:
        allowed: set[str] = set(MODEL_KINDS)
        seen: set[str] = set()
        for k in self.extra_kinds:
            if k not in allowed:
                raise ValueError(f"model {self.id!r} has invalid extra_kind {k!r}")
            if k in seen:
                raise ValueError(f"model {self.id!r} has duplicate extra_kind {k!r}")
            seen.add(k)
            if k == self.model_kind:
                raise ValueError(
                    f"model {self.id!r} extra_kinds must not repeat model_kind {k!r}"
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
                if kind not in MODEL_KINDS:
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
                if not spec.supports_kind(kind):
                    raise ValueError(
                        f"provider {prov.id!r} recommended_models[{kind!r}] points to "
                        f"{mid!r} but that model does not support kind {kind!r} "
                        f"(model_kind={spec.model_kind!r}, extra_kinds={spec.extra_kinds!r})"
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


@dataclass(frozen=True)
class CostEstimate:
    """Compact USD cost estimate from bundled catalog pricing."""

    currency: str
    estimated_total: float
    pricing_available: bool
    reason: str | None = None


class ModelCatalog:
    """In-memory view of catalog.yaml."""

    def __init__(self, doc: CatalogDocument) -> None:
        self._doc = doc
        self._providers_by_id: dict[str, Provider] = {p.id: p for p in doc.providers}
        self._models_by_id: dict[str, ModelSpec] = {m.id: m for m in doc.models}
        pricing_payload = [
            {
                "id": m.id,
                "pricing": m.pricing.model_dump(mode="json") if m.pricing is not None else None,
            }
            for m in doc.models
        ]
        pricing_hash = hashlib.sha256(
            json.dumps(pricing_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        self._pricing_version = f"{doc.catalog_version}:{pricing_hash}"

    @property
    def catalog_version(self) -> str:
        return self._doc.catalog_version

    @property
    def pricing_version(self) -> str:
        """Stable fingerprint for repricing rows: ``{catalog_version}:{hash12}``.

        Written to ``graph.log`` as a single CSV cell (colon is intentional, not a parse bug):
        catalog YAML ``catalog_version`` plus the first 12 hex chars of SHA-256 over sorted model
        ``id`` + ``pricing`` payloads.
        """
        return self._pricing_version

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
            if model_kind is not None and not m.supports_kind(model_kind):
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

    def estimate_token_usage_cost(
        self,
        *,
        model_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
    ) -> CostEstimate:
        """Estimate token cost using this catalog's PricingBlock."""
        spec = self.get_model(model_id)
        if spec is None:
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="model_not_in_catalog",
            )
        pricing = spec.pricing
        if pricing is None:
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="pricing_missing",
            )

        input_n = max(0, int(input_tokens))
        output_n = max(0, int(output_tokens))
        cached_n = min(max(0, int(cached_input_tokens)), input_n)
        uncached_input_n = input_n - cached_n

        total = 0.0
        if input_n > 0:
            input_rate = pricing.input_per_1m_tokens
            if input_rate is None:
                return CostEstimate(
                    currency="USD",
                    estimated_total=0.0,
                    pricing_available=False,
                    reason="input_pricing_missing",
                )
            cached_rate = pricing.cached_input_per_1m_tokens
            total += uncached_input_n * input_rate / 1_000_000
            effective_cached_rate = (
                cached_rate if cached_rate is not None else input_rate
            )
            total += cached_n * effective_cached_rate / 1_000_000
        if output_n > 0:
            output_rate = pricing.output_per_1m_tokens
            if output_rate is None:
                return CostEstimate(
                    currency="USD",
                    estimated_total=0.0,
                    pricing_available=False,
                    reason="output_pricing_missing",
                )
            total += output_n * output_rate / 1_000_000

        return CostEstimate(
            currency="USD",
            estimated_total=total,
            pricing_available=True,
        )

    def estimate_rerank_cost(
        self,
        *,
        model_id: str,
        processed_tokens: int = 0,
        search_units: int = 1,
    ) -> CostEstimate:
        """Estimate reranker cost — gross list price, free-tier quotas ignored.

        Two vendor shapes: Voyage-style per *processed* token
        (``processed = query_tokens × doc_count + sum(doc_tokens)``) and Cohere-style per *search
        unit* (one query + up to ~100 docs ≈ one unit). Local rerankers aren't catalogued → blank.
        """
        spec = self.get_model(model_id)
        if spec is None:
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="model_not_in_catalog",
            )
        pricing = spec.pricing
        if pricing is None:
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="pricing_missing",
            )
        tokens = max(0, int(processed_tokens))
        units = max(1, int(search_units))
        if pricing.per_1k_tokens is not None:
            return CostEstimate(
                currency="USD",
                estimated_total=tokens * pricing.per_1k_tokens / 1_000,
                pricing_available=True,
            )
        if pricing.input_per_1m_tokens is not None:
            return CostEstimate(
                currency="USD",
                estimated_total=tokens * pricing.input_per_1m_tokens / 1_000_000,
                pricing_available=True,
            )
        if pricing.estimated_usd_per_1k_searches is not None:
            return CostEstimate(
                currency="USD",
                estimated_total=units * pricing.estimated_usd_per_1k_searches / 1_000,
                pricing_available=True,
            )
        if pricing.estimated_usd_per_request is not None:
            return CostEstimate(
                currency="USD",
                estimated_total=units * pricing.estimated_usd_per_request,
                pricing_available=True,
            )
        return CostEstimate(
            currency="USD",
            estimated_total=0.0,
            pricing_available=False,
            reason="rerank_pricing_missing",
        )

    def estimate_image_gen_cost(
        self,
        *,
        model_id: str,
        steps: int = 1,
    ) -> CostEstimate:
        """Estimate diffusion image cost: ``per_image`` (fixed component) + ``steps × per_step``.

        Vendors price either a flat per-image rate (``per_image`` alone) or a fixed
        resolution component plus a per-step rate (Cloudflare Workers AI). Either field
        alone is enough for an estimate.
        """
        spec = self.get_model(model_id)
        if spec is None:
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="model_not_in_catalog",
            )
        if not spec.supports_kind("image_gen"):
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="model_not_image_gen",
            )
        pricing = spec.pricing
        if pricing is None or (pricing.per_image is None and pricing.per_step is None):
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="image_pricing_missing",
            )
        n_steps = max(1, int(steps))
        total = (pricing.per_image or 0.0) + n_steps * (pricing.per_step or 0.0)
        return CostEstimate(currency="USD", estimated_total=total, pricing_available=True)

    def estimate_tts_usage_cost(
        self,
        *,
        provider_id: str,
        model_id: str,
        input_characters: int = 0,
        input_text_tokens: int = 0,
        generated_audio_seconds: float = 0.0,
        output_audio_tokens: int = 0,
    ) -> CostEstimate:
        """Estimate TTS cost from provider/model-specific metering fields."""
        normalized_provider = _normalize_tts_provider_id(provider_id)
        if normalized_provider not in {"openai", "google"}:
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="unsupported_tts_provider",
            )

        canonical_model_id = _canonical_model_id(normalized_provider, model_id)
        spec = self.get_model(canonical_model_id)
        if spec is None:
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="model_not_in_catalog",
            )
        if not spec.supports_kind("tts"):
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="model_not_tts",
            )
        pricing = spec.pricing
        if pricing is None:
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="pricing_missing",
            )

        short_model = canonical_model_id.split(":", 1)[1]
        if normalized_provider == "openai" and short_model in {"tts-1", "tts-1-hd"}:
            chars = max(0, int(input_characters))
            rate_per_char = pricing.per_character
            if rate_per_char is None and pricing.estimated_usd_per_1k_chars_speech is not None:
                rate_per_char = pricing.estimated_usd_per_1k_chars_speech / 1_000
            if rate_per_char is None and pricing.output_per_1m_tokens is not None:
                rate_per_char = pricing.output_per_1m_tokens / 1_000_000
            if rate_per_char is None:
                return CostEstimate(
                    currency="USD",
                    estimated_total=0.0,
                    pricing_available=False,
                    reason="character_pricing_missing",
                )
            return CostEstimate(
                currency="USD",
                estimated_total=chars * rate_per_char,
                pricing_available=True,
            )

        if normalized_provider == "openai" and short_model == "gpt-4o-mini-tts":
            text_tokens = max(0, int(input_text_tokens))
            audio_seconds = max(0.0, float(generated_audio_seconds))
            if pricing.input_per_1m_tokens is None:
                return CostEstimate(
                    currency="USD",
                    estimated_total=0.0,
                    pricing_available=False,
                    reason="input_pricing_missing",
                )
            if pricing.output_per_1m_tokens is None:
                return CostEstimate(
                    currency="USD",
                    estimated_total=0.0,
                    pricing_available=False,
                    reason="output_pricing_missing",
                )
            total = (
                text_tokens * pricing.input_per_1m_tokens / 1_000_000
                + audio_seconds * pricing.output_per_1m_tokens / 48_000
            )
            return CostEstimate(
                currency="USD",
                estimated_total=total,
                pricing_available=True,
            )

        if normalized_provider == "google":
            text_tokens = max(0, int(input_text_tokens))
            audio_tokens = max(0, int(output_audio_tokens))
            if text_tokens <= 0 or audio_tokens <= 0:
                return CostEstimate(
                    currency="USD",
                    estimated_total=0.0,
                    pricing_available=False,
                    reason="tts_usage_metadata_missing",
                )
            if pricing.input_per_1m_tokens is None:
                return CostEstimate(
                    currency="USD",
                    estimated_total=0.0,
                    pricing_available=False,
                    reason="input_pricing_missing",
                )
            if pricing.output_per_1m_tokens is None:
                return CostEstimate(
                    currency="USD",
                    estimated_total=0.0,
                    pricing_available=False,
                    reason="output_pricing_missing",
                )
            total = (
                text_tokens * pricing.input_per_1m_tokens
                + audio_tokens * pricing.output_per_1m_tokens
            ) / 1_000_000
            return CostEstimate(
                currency="USD",
                estimated_total=total,
                pricing_available=True,
            )

        return CostEstimate(
            currency="USD",
            estimated_total=0.0,
            pricing_available=False,
            reason="unsupported_tts_model",
        )

    def estimate_stt_usage_cost(
        self,
        *,
        provider_id: str,
        model_id: str,
        audio_seconds: float = 0.0,
        audio_tokens: int = 0,
        output_tokens: int = 0,
    ) -> CostEstimate:
        """Estimate STT cost (mirrors ``estimate_tts_usage_cost``).

        Token-based when provider usage is available — ``(audio_tokens × audio-input-rate) +
        (output_tokens × output-rate)`` per ``docs/model_pricing.md``. Falls back to a duration
        ``per_second`` estimate (e.g. whisper-style, or before usage is wired). For STT-only models
        ``input_per_1m_tokens`` is the audio-input rate; dual-use chat models approximate with it.
        """
        canonical = model_id if ":" in model_id else f"{(provider_id or '').strip()}:{model_id}"
        spec = self.get_model(canonical)
        if spec is None:
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="model_not_in_catalog",
            )
        if not spec.supports_kind("stt"):
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="model_not_stt",
            )
        pricing = spec.pricing
        if pricing is None:
            return CostEstimate(
                currency="USD",
                estimated_total=0.0,
                pricing_available=False,
                reason="pricing_missing",
            )
        audio_tok = max(0, int(audio_tokens))
        output_tok = max(0, int(output_tokens))
        # Audio-input rate: the dedicated field, else input_per_1m_tokens ONLY for STT-only models
        # (where input is audio). Dual-use chat models without the field are not text-rate-approximated.
        audio_rate = pricing.audio_input_per_1m_tokens
        if audio_rate is None and spec.model_kind == "stt":
            audio_rate = pricing.input_per_1m_tokens
        if audio_tok > 0 and audio_rate is not None and pricing.output_per_1m_tokens is not None:
            total = (
                audio_tok * audio_rate + output_tok * pricing.output_per_1m_tokens
            ) / 1_000_000
            return CostEstimate(currency="USD", estimated_total=total, pricing_available=True)
        if pricing.per_second is not None:
            total = max(0.0, float(audio_seconds)) * pricing.per_second
            return CostEstimate(currency="USD", estimated_total=total, pricing_available=True)
        return CostEstimate(
            currency="USD",
            estimated_total=0.0,
            pricing_available=False,
            reason="stt_pricing_missing",
        )


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


def _normalize_tts_provider_id(provider_id: str) -> str:
    value = str(provider_id or "").strip().lower()
    if value == "gemini":
        return "google"
    return value


def _canonical_model_id(provider_id: str, model_id: str) -> str:
    value = str(model_id or "").strip()
    if ":" in value:
        return value
    return f"{provider_id}:{value}"
