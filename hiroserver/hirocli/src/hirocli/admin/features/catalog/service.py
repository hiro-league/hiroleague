"""Catalog browser — wraps LLM catalog tools; no NiceGUI (guidelines §1.3)."""

from __future__ import annotations

from typing import Any

from hirocli.tools.llm_catalog import (
    LlmCatalogListModelsTool,
    LlmCatalogListProvidersTool,
)

from hirocli.admin.shared.result import Result


class CatalogBrowserService:
    """Facade over read-only catalog tools for the admin UI."""

    def list_providers(self, hosting: str | None = None) -> Result[list[dict[str, Any]]]:
        try:
            raw = (
                LlmCatalogListProvidersTool().execute(hosting=hosting)
                if hosting
                else LlmCatalogListProvidersTool().execute()
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(list(raw.providers))

    def list_models(
        self,
        *,
        provider_id: str | None = None,
        model_kind: str | None = None,
        model_class: str | None = None,
        hosting: str | None = None,
    ) -> Result[tuple[int, list[dict[str, Any]]]]:
        """Return (catalog_version, models) for table display."""
        kwargs: dict[str, Any] = {}
        if provider_id:
            kwargs["provider_id"] = provider_id
        if model_kind:
            kwargs["model_kind"] = model_kind
        if model_class:
            kwargs["model_class"] = model_class
        if hosting:
            kwargs["hosting"] = hosting
        try:
            raw = LlmCatalogListModelsTool().execute(**kwargs)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success((raw.catalog_version, list(raw.models)))
