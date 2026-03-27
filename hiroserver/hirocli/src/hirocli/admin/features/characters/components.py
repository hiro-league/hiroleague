"""Characters UI fragments — cards and avatars (guidelines §1.2)."""

from __future__ import annotations

from nicegui import ui


def character_avatar_thumbnail(photo_data_url: str | None, *, size_class: str = "w-16 h-16") -> None:
    """Rounded preview or muted placeholder (encourages photo upload per design doc)."""
    if photo_data_url:
        ui.image(photo_data_url).classes(f"{size_class} rounded object-cover border border-grey-4")
    else:
        with ui.column().classes(
            f"items-center justify-center {size_class} rounded "
            "bg-grey-2 border border-dashed border-grey-4"
        ):
            ui.icon("face").classes("text-2xl opacity-35")
            ui.label("No photo").classes("text-xs opacity-50 leading-tight text-center px-1")
