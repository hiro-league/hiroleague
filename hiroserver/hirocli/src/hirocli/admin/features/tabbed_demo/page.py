"""Tabbed demo — thin page with URL query params for deep-linking (guidelines §1.2, §1.6).

Examples:
    /tabbed-demo                                -> Planets tab, no filter
    /tabbed-demo?tab=moons                      -> Moons tab (all moons)
    /tabbed-demo?tab=moons&planet_id=jupiter    -> Moons tab filtered by Jupiter
    /tabbed-demo?tab=planets&planet_type=Gas+giant -> Planets tab filtered by type
"""

from __future__ import annotations

from hirocli.admin.features.tabbed_demo.controller import TabbedDemoController
from hirocli.admin.router import admin_router
from hirocli.admin.shared.tab_nav import TabNavRequest
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/tabbed-demo")
async def tabbed_demo_page(
    tab: str = "planets",
    planet_id: str | None = None,
    planet_type: str | None = None,
) -> None:
    create_page_layout(active_path="/tabbed-demo")
    nav = TabNavRequest(
        tab=tab,
        filters={"planet_id": planet_id, "planet_type": planet_type},
    )
    await TabbedDemoController(nav).mount()
