"""Catalog browser — tabbed catalog providers + models (guidelines §1.6, §2.3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import app, run, ui

from hirocli.admin.features.catalog.components import (
    catalog_models_table,
    catalog_providers_table,
)
from hirocli.admin.features.catalog.service import CatalogBrowserService
from hirocli.admin.shared.formatters import format_pricing_summary
from hirocli.admin.shared.result import Result
from hirocli.admin.shared.tab_nav import TabNavRequest
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

TABS = ["providers", "models"]
DEFAULT_TAB = "providers"
STORAGE_KEY = "catalog.active_tab"
PAGE_PATH = "/catalog"


class CatalogPageController:
    """Read-only bundled catalog reference for admins."""

    def __init__(self, nav: TabNavRequest | None = None) -> None:
        self._service = CatalogBrowserService()
        self._nav = nav
        self._filters: dict[str, dict[str, Any]] = {
            "providers": {},
            "models": {
                "provider_id": "",
                "model_kind": "",
                "model_class": "",
                "hosting": "",
            },
        }
        self._loaded: set[str] = set()
        self._refresh_providers: Callable[[], None] | None = None
        self._refresh_models: Callable[[], None] | None = None
        self._prov_sel: ui.select | None = None
        self._kind_sel: ui.select | None = None
        self._class_sel: ui.select | None = None
        self._host_sel: ui.select | None = None

    def _init_tab_state(self) -> None:
        """Resolve initial tab and seed model filters from URL. Requires WebSocket (storage.tab)."""
        nav = self._nav
        initial = (nav and nav.tab) or app.storage.tab.get(STORAGE_KEY) or DEFAULT_TAB
        if initial not in TABS:
            initial = DEFAULT_TAB
        app.storage.tab[STORAGE_KEY] = initial

        if nav:
            self._filters["providers"] = nav.filter_for("providers")
            mf = nav.filter_for("models")
            for k, v in mf.items():
                if k in self._filters["models"] and v is not None:
                    self._filters["models"][k] = v

    def _norm_filter(self, raw: str | None) -> str | None:
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
        f = self._filters["models"]
        return self._service.list_models(
            provider_id=self._norm_filter(f.get("provider_id")),
            model_kind=self._norm_filter(f.get("model_kind")),
            model_class=self._norm_filter(f.get("model_class")),
            hosting=self._norm_filter(f.get("hosting")),
        )

    def _sync_filters_from_selects(self) -> None:
        if self._prov_sel is not None:
            self._filters["models"]["provider_id"] = str(self._prov_sel.value or "")
        if self._kind_sel is not None:
            self._filters["models"]["model_kind"] = str(self._kind_sel.value or "")
        if self._class_sel is not None:
            self._filters["models"]["model_class"] = str(self._class_sel.value or "")
        if self._host_sel is not None:
            self._filters["models"]["hosting"] = str(self._host_sel.value or "")

    def _on_filter_change(self) -> None:
        self._sync_filters_from_selects()
        if self._refresh_models:
            self._refresh_models()
        if app.storage.tab.get(STORAGE_KEY) == "models":
            self._sync_url("models")

    def _on_tab_switch(self, e) -> None:
        tab = e.value
        self._mark_loaded(tab)
        self._sync_url(tab)

    def _mark_loaded(self, tab: str) -> None:
        if tab not in self._loaded:
            self._loaded.add(tab)
            if tab == "providers" and self._refresh_providers:
                self._refresh_providers()
            elif tab == "models" and self._refresh_models:
                self._refresh_models()

    def open_models_for_provider(self, provider_id: str) -> None:
        """Cross-tab: Catalog providers name click -> Models tab filtered by provider (§1.6.3)."""
        self._filters["models"]["provider_id"] = provider_id
        app.storage.tab[STORAGE_KEY] = "models"
        self._loaded.add("models")
        if self._refresh_models:
            self._refresh_models()
        self._sync_url("models")

    def _sync_url(self, tab: str) -> None:
        from urllib.parse import urlencode

        params: dict[str, str] = {"tab": tab}
        if tab == "models":
            pid = self._filters["models"].get("provider_id") or ""
            if pid:
                params["provider_id"] = str(pid)
        query = urlencode(params)
        ui.run_javascript(f"history.replaceState(null, '', '{PAGE_PATH}?{query}')")

    def _clear_filters(self) -> None:
        self._filters["models"] = {
            "provider_id": "",
            "model_kind": "",
            "model_class": "",
            "hosting": "",
        }
        if self._refresh_models:
            self._refresh_models()
        if app.storage.tab.get(STORAGE_KEY) == "models":
            self._sync_url("models")

    async def mount(self) -> None:
        await ui.context.client.connected()
        self._init_tab_state()
        initial_tab = app.storage.tab[STORAGE_KEY]

        @ui.refreshable
        async def render_providers() -> None:
            if "providers" not in self._loaded:
                loading_state(message="Loading catalog…")
                return

            prov_res = await run.io_bound(self._service.list_providers, None)
            if not prov_res.ok:
                error_banner(
                    message=prov_res.error or "Failed to load catalog",
                    on_retry=lambda: self._refresh_providers and self._refresh_providers(),
                )
                return
            providers = prov_res.data or []
            prov_rows = self._provider_table_rows(providers)
            ui.label("Catalog providers").classes("text-lg font-semibold")
            if prov_rows:
                ui.label(
                    "Click a provider name to view its models on the Models tab."
                ).classes("text-sm opacity-70 mb-2")
            if not prov_rows:
                empty_state(message="No providers in the bundled catalog.", icon="cloud_off")
            else:
                tbl = catalog_providers_table(
                    prov_rows,
                    on_select_provider=self.open_models_for_provider,
                )
                if tbl is not None:
                    tbl.classes("w-full")

        @ui.refreshable
        async def render_models() -> None:
            if "models" not in self._loaded:
                loading_state(message="Loading models…")
                return

            prov_res = await run.io_bound(self._service.list_providers, None)
            if not prov_res.ok:
                error_banner(
                    message=prov_res.error or "Failed to load catalog",
                    on_retry=lambda: self._refresh_models and self._refresh_models(),
                )
                return
            providers = prov_res.data or []
            provider_labels = {
                p["id"]: f"{p.get('display_name', p['id'])} ({p['id']})"
                for p in providers
            }
            f = self._filters["models"]

            ui.label("Models").classes("text-lg font-semibold")
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
                    value=f.get("provider_id") or "",
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
                    value=f.get("model_kind") or "",
                    label="Kind",
                    on_change=lambda _: self._on_filter_change(),
                ).classes("min-w-[10rem]").props("dense outlined")

                class_labels = {
                    "": "All classes",
                    **{c: c for c in _MODEL_CLASS_OPTIONS if c},
                }
                self._class_sel = ui.select(
                    class_labels,
                    value=f.get("model_class") or "",
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
                    value=f.get("hosting") or "",
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
                    on_retry=lambda: self._refresh_models and self._refresh_models(),
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

        self._refresh_providers = render_providers.refresh
        self._refresh_models = render_models.refresh

        with ui.column().classes("w-full gap-6 p-6"):
            ui.label("LLM catalog").classes("text-2xl font-semibold")
            ui.label(
                "Read-only reference: bundled providers and models (pricing, kinds, capabilities). "
                "Workspace credentials are managed on the Providers page."
            ).classes("text-sm opacity-70 max-w-3xl")

            with ui.tabs(value=initial_tab).bind_value(app.storage.tab, STORAGE_KEY) as tabs:
                ui.tab("providers", label="Catalog providers", icon="cloud")
                ui.tab("models", label="Models", icon="table_chart")

            tabs.on_value_change(self._on_tab_switch)

            with ui.tab_panels(tabs, value=initial_tab).bind_value(
                app.storage.tab, STORAGE_KEY
            ).classes("w-full"):
                with ui.tab_panel("providers"):
                    await render_providers()
                with ui.tab_panel("models"):
                    await render_models()

        self._mark_loaded(initial_tab)
