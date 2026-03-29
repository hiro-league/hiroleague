"""Tabbed demo controller — reference implementation of §1.6 tabbed page pattern.

Demonstrates:
- Single source of truth for active tab (bind_value to storage)
- Lazy loading per tab (only fetch data when tab first activated)
- Per-tab filter state seeded from URL query params
- Intra-page cross-tab navigation (planets → moons filtered by planet)
- on_value_change for tab switch detection (not Quasar 'transition' event)
- Browser URL sync via history.replaceState (shareable deep links)
"""

from __future__ import annotations

from nicegui import app, ui

from hirocli.admin.features.tabbed_demo import components
from hirocli.admin.features.tabbed_demo.moons_service import MoonsService
from hirocli.admin.features.tabbed_demo.planets_service import PlanetsService
from hirocli.admin.shared.tab_nav import TabNavRequest
from hirocli.admin.shared.ui.error_banner import error_banner
from hirocli.admin.shared.ui.loading_state import loading_state


TABS = ["planets", "moons"]
DEFAULT_TAB = "planets"
STORAGE_KEY = "tabbed_demo.active_tab"
PAGE_PATH = "/tabbed-demo"


class TabbedDemoController:

    def __init__(self, nav: TabNavRequest | None = None) -> None:
        self._planets_svc = PlanetsService()
        self._moons_svc = MoonsService()
        self._nav = nav
        self._filters: dict[str, dict] = {t: {} for t in TABS}
        self._loaded: set[str] = set()

    # ── Build ────────────────────────────────────────────────

    def _init_tab_state(self) -> None:
        """Resolve initial tab and seed filters. Must run after client connection
        is established — app.storage.tab requires the WebSocket handshake."""
        nav = self._nav
        initial = (nav and nav.tab) or app.storage.tab.get(STORAGE_KEY) or DEFAULT_TAB
        if initial not in TABS:
            initial = DEFAULT_TAB
        app.storage.tab[STORAGE_KEY] = initial

        if nav:
            for t in TABS:
                self._filters[t] = nav.filter_for(t)

    async def mount(self) -> None:
        # app.storage.tab requires the WebSocket client connection
        await ui.context.client.connected()
        self._init_tab_state()
        initial_tab = app.storage.tab[STORAGE_KEY]

        with ui.column().classes("w-full gap-0 p-6"):
            ui.label("Tabbed page demo").classes("text-2xl font-semibold")
            ui.label(
                "Live reference for the tabbed page pattern (guidelines §1.6). "
                "Click a planet's satellite icon to switch to the Moons tab filtered by that planet."
            ).classes("text-sm opacity-70 max-w-3xl mb-4")

            # value= seeds the initial render; bind_value keeps it synced with storage.
            # Both must use the same storage key (§1.6.2 rule 1).
            with ui.tabs(value=initial_tab).bind_value(app.storage.tab, STORAGE_KEY) as tabs:
                ui.tab("planets", label="Planets", icon="public")
                ui.tab("moons", label="Moons", icon="satellite_alt")

            # §1.6.2 rule 5: on_value_change, NOT Quasar 'transition' event
            tabs.on_value_change(self._on_tab_switch)

            with ui.tab_panels(tabs, value=initial_tab).bind_value(
                app.storage.tab, STORAGE_KEY
            ).classes("w-full"):
                with ui.tab_panel("planets"):
                    self._render_planets()
                with ui.tab_panel("moons"):
                    self._render_moons()

        # Trigger data load for whichever tab is initially active
        self._mark_loaded(initial_tab)

    # ── Tab switching ────────────────────────────────────────

    def _on_tab_switch(self, e) -> None:
        self._mark_loaded(e.value)
        self._sync_url(e.value)

    def _mark_loaded(self, tab: str) -> None:
        if tab not in self._loaded:
            self._loaded.add(tab)
            refreshable = getattr(self, f"_render_{tab}", None)
            if refreshable:
                refreshable.refresh()

    def switch_to_tab(self, tab: str, **filters) -> None:
        """Intra-page navigation with optional filters (§1.6.3)."""
        self._filters[tab] = filters
        app.storage.tab[STORAGE_KEY] = tab
        self._loaded.add(tab)
        getattr(self, f"_render_{tab}").refresh()
        self._sync_url(tab)

    # ── URL sync ─────────────────────────────────────────────

    def _sync_url(self, tab: str) -> None:
        """Update browser address bar to match current tab + filters (no reload).

        Uses history.replaceState so the URL is always a shareable deep link
        without polluting browser history with every tab switch.
        """
        from urllib.parse import urlencode

        params: dict[str, str] = {"tab": tab}
        for k, v in self._filters.get(tab, {}).items():
            if v is not None:
                params[k] = str(v)
        query = urlencode(params)
        ui.run_javascript(f"history.replaceState(null, '', '{PAGE_PATH}?{query}')")

    # ── Tab content (one @ui.refreshable per tab) ────────────

    @ui.refreshable
    def _render_planets(self) -> None:
        # §1.6.2 rule 2: guard with _loaded check for lazy loading
        if "planets" not in self._loaded:
            loading_state()
            return

        planet_type = self._filters["planets"].get("planet_type")
        result = self._planets_svc.list(planet_type=planet_type)
        if not result.ok:
            error_banner(message=result.error or "Failed to load planets", on_retry=self._render_planets.refresh)
            return

        if planet_type:
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.label(f"Filtered by type: {planet_type}").classes("text-sm opacity-70")
                ui.button("Clear", on_click=self._clear_planet_filter).props("flat dense size=sm")

        # Cross-tab action: clicking satellite icon switches to moons tab filtered by planet
        components.planets_table(
            result.data or [],
            on_view_moons=lambda planet_id: self.switch_to_tab("moons", planet_id=planet_id),
        )

    @ui.refreshable
    def _render_moons(self) -> None:
        if "moons" not in self._loaded:
            loading_state()
            return

        planet_id = self._filters["moons"].get("planet_id")
        result = self._moons_svc.list(planet_id=planet_id)
        if not result.ok:
            error_banner(message=result.error or "Failed to load moons", on_retry=self._render_moons.refresh)
            return

        if planet_id:
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.label(f"Showing moons of: {planet_id}").classes("text-sm opacity-70")
                ui.button("Show all", on_click=self._clear_moon_filter).props("flat dense size=sm")

        components.moons_table(result.data or [], planet_filter=planet_id)

    # ── Filter helpers ───────────────────────────────────────

    def _clear_planet_filter(self) -> None:
        self._filters["planets"] = {}
        self._render_planets.refresh()
        self._sync_url("planets")

    def _clear_moon_filter(self) -> None:
        self._filters["moons"] = {}
        self._render_moons.refresh()
        self._sync_url("moons")
