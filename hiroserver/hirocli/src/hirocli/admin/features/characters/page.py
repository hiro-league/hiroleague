"""Characters — thin page; controller owns UI (guidelines §1.2)."""

from __future__ import annotations

from hirocli.admin.features.characters.controller import CharactersPageController
from hirocli.admin.router import admin_router
from hirocli.admin.shell.layout import create_page_layout


@admin_router.page("/characters")
async def characters_page() -> None:
    create_page_layout(active_path="/characters")
    await CharactersPageController().mount()
