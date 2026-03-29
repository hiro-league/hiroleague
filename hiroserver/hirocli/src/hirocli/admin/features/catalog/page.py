"""LLM catalog browser — thin page with tab deep-links (guidelines §1.2, §1.6).

Examples:
    /catalog                              -> Catalog providers tab
    /catalog?tab=models                   -> Models tab (all models)
    /catalog?tab=models&provider_id=openai -> Models tab filtered to one provider
"""

from __future__ import annotations

from hirocli.admin.features.catalog.controller import CatalogPageController
from hirocli.admin.router import admin_router
from hirocli.admin.shared.tab_nav import TabNavRequest
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/catalog")
async def catalog_page(
    tab: str = "providers",
    provider_id: str | None = None,
) -> None:
    create_page_layout(active_path="/catalog")
    nav = TabNavRequest(
        tab=tab,
        filters={"provider_id": provider_id},
    )
    await CatalogPageController(nav).mount()
