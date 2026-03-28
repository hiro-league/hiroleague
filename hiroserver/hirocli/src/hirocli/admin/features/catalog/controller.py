"""Catalog browser — filters, provider summary, models table (guidelines §2.3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import run, ui

from hirocli.admin.shared.result import Result

from hirocli.admin.features.catalog.components import (
    catalog_models_table,
    catalog_providers_table,
)
from hirocli.admin.features.catalog.service import CatalogBrowserService
from hirocli.admin.shared.formatters import format_pricing_summary
from hirocli.admin.shared.ui.empty_state import empty_state
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state

_MODEL_CLASS_OPTIONS = (
    "",
    "agentic",
    "fast",
    "balanced",
    "reasoning",
    "creative",
    "coding",
)


class CatalogPageController:
    """Read-only bundled catalog reference for admins."""

    def __init__(self) -> None:
        self._service = CatalogBrowserService()
        self._refresh_main: Callable[[], None] | None = None
        self._filter_provider = ""
        self._filter_kind = ""
        self._filter_class = ""
        self._filter_hosting = ""
        self._prov_sel: ui.select | None = None
        self._kind_sel: ui.select | None = None
        self._class_sel: ui.select | None = None
        self._host_sel: ui.select | None = None

    def _refresh(self) -> None:
        if self._refresh_main:
            self._refresh_main()

    def _norm_filter(self, raw: str) -> str | None:
        s = (raw or "").strip()
        return None if s == "" else s

    def _provider_table_rows(self, providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for p in providers:
            keys = p.get("credential_env_keys") or []
            out.append(
                {
                    **p,
                    "credential_env_keys": ", ".join(keys) if keys else "—",
                }
            )
        return out

    def _model_table_rows(
        self,
        models: list[dict[str, Any]],
        provider_labels: dict[str, str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for m in models:
            pid = str(m.get("provider_id", ""))
            kind = str(m.get("model_kind", ""))
            hosting = m.get("hosting")
            pricing = m.get("pricing")
            feats = m.get("features") or []
            if isinstance(feats, list):
                feat_str = ", ".join(sorted(str(x) for x in feats))
            else:
                feat_str = str(feats)
            ctx = m.get("context_window")
            ctx_s = f"{ctx:,}" if isinstance(ctx, int) else "—"
            mc = m.get("model_class")
            rows.append(
                {
                    "id": m["id"],
                    "provider_label": provider_labels.get(pid, pid),
                    "model_label": f"{m.get('display_name', '')} ({m.get('id', '')})",
                    "model_kind": kind,
                    "model_class": mc if mc else "—",
                    "hosting": hosting or "—",
                    "context_window": ctx_s,
                    "pricing": format_pricing_summary(
                        pricing if isinstance(pricing, dict) else None,
                        kind,
                        hosting=str(hosting) if hosting else None,
                    ),
                    "features": feat_str if feat_str else "—",
                }
            )
        return rows

    def _list_models_filtered(self) -> Result[tuple[int, list[dict[str, Any]]]]:
        return self._service.list_models(
            provider_id=self._norm_filter(self._filter_provider),
            model_kind=self._norm_filter(self._filter_kind),
            model_class=self._norm_filter(self._filter_class),
            hosting=self._norm_filter(self._filter_hosting),
        )

    def _sync_filters_from_selects(self) -> None:
        if self._prov_sel is not None:
            self._filter_provider = str(self._prov_sel.value or "")
        if self._kind_sel is not None:
            self._filter_kind = str(self._kind_sel.value or "")
        if self._class_sel is not None:
            self._filter_class = str(self._class_sel.value or "")
        if self._host_sel is not None:
            self._filter_hosting = str(self._host_sel.value or "")

    def _on_filter_change(self) -> None:
        self._sync_filters_from_selects()
        self._refresh()

    async def mount(self) -> None:
        @ui.refreshable
        async def main_body() -> None:
            with ui.column().classes("w-full") as holder:
                with holder:
                    loading_state(message="Loading catalog…")
                prov_res = await run.io_bound(self._service.list_providers, None)
                holder.clear()
                with holder:
                    if not prov_res.ok:
                        error_banner(
                            message=prov_res.error or "Failed to load catalog",
                            on_retry=self._refresh,
                        )
                        return
                    providers = prov_res.data or []
                    provider_labels = {
                        p["id"]: f"{p.get('display_name', p['id'])} ({p['id']})"
                        for p in providers
                    }

                    ui.label("Providers in catalog").classes("text-lg font-semibold mt-2")
                    prov_rows = self._provider_table_rows(providers)
                    catalog_providers_table(prov_rows)

                    ui.label("Models").classes("text-lg font-semibold mt-6")
                    filt = ui.row().classes("w-full flex-wrap gap-4 items-end")
                    with filt:
                        prov_opts = {
                            "": "All providers",
                            **{
                                p["id"]: f"{p.get('display_name', p['id'])} ({p['id']})"
                                for p in providers
                            },
                        }
                        self._prov_sel = ui.select(
                            prov_opts,
                            value=self._filter_provider,
                            label="Provider",
                            on_change=lambda _: self._on_filter_change(),
                        ).classes("min-w-[14rem]").props("dense outlined")

                        kind_opts = {
                            "": "All kinds",
                            "chat": "chat",
                            "tts": "tts",
                            "stt": "stt",
                            "embedding": "embedding",
                            "image_gen": "image_gen",
                        }
                        self._kind_sel = ui.select(
                            kind_opts,
                            value=self._filter_kind,
                            label="Kind",
                            on_change=lambda _: self._on_filter_change(),
                        ).classes("min-w-[10rem]").props("dense outlined")

                        class_labels = {
                            "": "All classes",
                            **{c: c for c in _MODEL_CLASS_OPTIONS if c},
                        }
                        self._class_sel = ui.select(
                            class_labels,
                            value=self._filter_class,
                            label="Class",
                            on_change=lambda _: self._on_filter_change(),
                        ).classes("min-w-[10rem]").props("dense outlined")

                        host_opts = {
                            "": "All hosting",
                            "cloud": "cloud",
                            "local": "local",
                        }
                        self._host_sel = ui.select(
                            host_opts,
                            value=self._filter_hosting,
                            label="Hosting",
                            on_change=lambda _: self._on_filter_change(),
                        ).classes("min-w-[10rem]").props("dense outlined")

                        ui.button("Clear filters", icon="filter_alt_off", on_click=self._clear_filters).props(
                            "flat dense"
                        )

                    models_res = await run.io_bound(self._list_models_filtered)
                    if not models_res.ok:
                        error_banner(
                            message=models_res.error or "Failed to list models",
                            on_retry=self._refresh,
                        )
                        return
                    assert models_res.data is not None
                    _version, model_dicts = models_res.data
                    if not model_dicts:
                        empty_state(
                            message="No models match the current filters.",
                            icon="search_off",
                        )
                    else:
                        ui.label(f"Catalog version {_version}").classes("text-xs opacity-60 mb-1")
                        mrows = self._model_table_rows(model_dicts, provider_labels)
                        catalog_models_table(mrows)

        self._refresh_main = main_body.refresh

        with ui.column().classes("w-full gap-6 p-6"):
            ui.label("LLM catalog").classes("text-2xl font-semibold")
            ui.label(
                "Read-only reference: bundled providers and models (pricing, kinds, capabilities). "
                "Workspace credentials are managed on the Providers page."
            ).classes("text-sm opacity-70 max-w-3xl")

        await main_body()

    def _clear_filters(self) -> None:
        self._filter_provider = ""
        self._filter_kind = ""
        self._filter_class = ""
        self._filter_hosting = ""
        if self._prov_sel is not None:
            self._prov_sel.value = ""
        if self._kind_sel is not None:
            self._kind_sel.value = ""
        if self._class_sel is not None:
            self._class_sel.value = ""
        if self._host_sel is not None:
            self._host_sel.value = ""
        self._refresh()
