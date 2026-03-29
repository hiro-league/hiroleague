"""Characters — tabbed browse + detail (view/edit); thin page (guidelines §1.2, §1.6)."""

from __future__ import annotations

from hirocli.admin.features.characters.controller import CharactersPageController
from hirocli.admin.router import admin_router
from hirocli.admin.shared.tab_nav import TabNavRequest
from hirocli.admin.shell.layout import create_page_layout

TABS = frozenset({"browse", "detail"})


@admin_router.page("/characters")
async def characters_page(
    tab: str = "browse",
    character_id: str | None = None,
    mode: str | None = None,
) -> None:
    create_page_layout(active_path="/characters")
    url_tab = tab if tab in TABS else "browse"
    eff_mode = mode if mode in ("view", "edit") else ("edit" if not character_id else "view")
    # Avoid leaking detail query params into Browse (TabNavRequest.filter_for semantics).
    detail_filters = (
        {"character_id": character_id, "mode": eff_mode} if url_tab == "detail" else {}
    )
    nav = TabNavRequest(tab=url_tab, filters=detail_filters)
    await CharactersPageController(nav).mount()
