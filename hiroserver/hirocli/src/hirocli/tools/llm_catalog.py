"""LLM catalog tools — read-only discovery of bundled providers and models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.model_catalog import Hosting, ModelKind, get_model_catalog
from .base import Tool, ToolParam


def _dump_provider_row(p: Any) -> dict[str, Any]:
    return p.model_dump(mode="json")


def _dump_model_row(m: Any, *, hosting: str | None) -> dict[str, Any]:
    row = m.model_dump(mode="json")
    row["hosting"] = hosting
    return row


@dataclass
class LlmCatalogListProvidersResult:
    catalog_version: str
    providers: list[dict[str, Any]]


@dataclass
class LlmCatalogListModelsResult:
    catalog_version: str
    models: list[dict[str, Any]]


@dataclass
class LlmCatalogGetModelResult:
    catalog_version: str
    model: dict[str, Any]
    provider: dict[str, Any]


class LlmCatalogListProvidersTool(Tool):
    name = "llm_catalog_list_providers"
    description = (
        "List AI providers known to Hiro (OpenAI, Google, Anthropic, local runtimes). "
        "Each entry includes hosting type (cloud vs local), required credential env var "
        "names, metadata dates, and optional tts_voices presets for bundled TTS. "
        "Optional filter by hosting."
    )
    params = {
        "hosting": ToolParam(
            str,
            "Filter: 'cloud' or 'local' (omit for all providers)",
            required=False,
        ),
    }

    def execute(self, **kwargs: Any) -> LlmCatalogListProvidersResult:
        raw = kwargs.get("hosting")
        hosting: Hosting | None = None
        if raw is not None and str(raw).strip() != "":
            s = str(raw).strip().lower()
            if s not in ("cloud", "local"):
                raise ValueError("hosting must be 'cloud' or 'local' when provided")
            hosting = s  # type: ignore[assignment]
        cat = get_model_catalog()
        providers = cat.list_providers(hosting=hosting)
        return LlmCatalogListProvidersResult(
            catalog_version=cat.catalog_version,
            providers=[_dump_provider_row(p) for p in providers],
        )


class LlmCatalogListModelsTool(Tool):
    name = "llm_catalog_list_models"
    description = (
        "List models in the Hiro catalog with optional filters: provider_id, model_kind "
        "(chat, tts, stt, embedding, image_gen — includes rows whose primary or extra_kinds "
        "match), model_class (e.g. agentic, fast), "
        "or hosting (cloud vs local). Each row includes pricing metadata when present."
    )
    params = {
        "provider_id": ToolParam(
            str,
            "Filter by provider id, e.g. 'openai'",
            required=False,
        ),
        "model_kind": ToolParam(
            str,
            "Filter by kind: chat, tts, stt, embedding, image_gen (matches primary model_kind or extra_kinds)",
            required=False,
        ),
        "model_class": ToolParam(
            str,
            "Filter by curated class, e.g. 'agentic', 'fast', 'balanced'",
            required=False,
        ),
        "hosting": ToolParam(
            str,
            "Filter: 'cloud' or 'local'",
            required=False,
        ),
    }

    def execute(self, **kwargs: Any) -> LlmCatalogListModelsResult:
        cat = get_model_catalog()
        provider_id = kwargs.get("provider_id")
        model_kind_raw = kwargs.get("model_kind")
        model_class = kwargs.get("model_class")
        hosting_raw = kwargs.get("hosting")

        pid = str(provider_id).strip() if provider_id not in (None, "") else None
        if pid == "":
            pid = None

        model_kind: ModelKind | None = None
        if model_kind_raw is not None and str(model_kind_raw).strip() != "":
            mk = str(model_kind_raw).strip().lower()
            allowed: tuple[ModelKind, ...] = (
                "chat",
                "tts",
                "stt",
                "embedding",
                "image_gen",
            )
            if mk not in allowed:
                raise ValueError(
                    f"model_kind must be one of {', '.join(allowed)} when provided"
                )
            model_kind = mk  # type: ignore[assignment]

        mc = str(model_class).strip() if model_class not in (None, "") else None
        if mc == "":
            mc = None

        hosting: Hosting | None = None
        if hosting_raw is not None and str(hosting_raw).strip() != "":
            h = str(hosting_raw).strip().lower()
            if h not in ("cloud", "local"):
                raise ValueError("hosting must be 'cloud' or 'local' when provided")
            hosting = h  # type: ignore[assignment]

        models = cat.list_models(
            provider_id=pid,
            model_kind=model_kind,
            model_class=mc,
            hosting=hosting,
        )
        rows: list[dict[str, Any]] = []
        for m in models:
            prov = cat.get_provider(m.provider_id)
            h = prov.hosting if prov else None
            rows.append(_dump_model_row(m, hosting=h))
        return LlmCatalogListModelsResult(
            catalog_version=cat.catalog_version,
            models=rows,
        )


class LlmCatalogGetModelTool(Tool):
    name = "llm_catalog_get_model"
    description = (
        "Return full catalog metadata for one model by canonical id (e.g. "
        "'openai:gpt-5.4'), including pricing block and parent provider summary."
    )
    params = {
        "model_id": ToolParam(
            str,
            "Canonical model id: provider:api_id, e.g. openai:gpt-5.4",
        ),
    }

    def execute(self, **kwargs: Any) -> LlmCatalogGetModelResult:
        mid = str(kwargs.get("model_id", "")).strip()
        if not mid:
            raise ValueError("model_id is required")
        cat = get_model_catalog()
        spec = cat.get_model(mid)
        if spec is None:
            raise ValueError(f"Unknown model id: {mid}")
        prov = cat.get_provider(spec.provider_id)
        if prov is None:
            raise ValueError(f"Model {mid} has missing provider {spec.provider_id}")
        model_row = spec.model_dump(mode="json")
        model_row["hosting"] = prov.hosting
        return LlmCatalogGetModelResult(
            catalog_version=cat.catalog_version,
            model=model_row,
            provider=_dump_provider_row(prov),
        )
