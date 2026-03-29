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


def markdown_split_row(
    *,
    label: str,
    value: str,
) -> ui.textarea:
    """Monospace textarea plus live markdown preview (edit mode; no WYSIWYG)."""
    with ui.row().classes("w-full gap-4 flex-wrap items-start"):
        with ui.column().classes("flex-1 min-w-72 gap-1"):
            ta = (
                ui.textarea(label=label, value=value)
                .classes("w-full font-mono text-sm")
                .props("outlined rows=12")
            )
        with ui.column().classes("flex-1 min-w-72 gap-1"):
            ui.label("Preview").classes("text-xs opacity-60")
            preview = ui.markdown(value or "—").classes(
                "w-full border border-grey-4 rounded p-3 bg-grey-1"
            )

    def _sync_preview() -> None:
        preview.content = (ta.value or "").strip() or "—"

    ta.on_value_change(_sync_preview)
    _sync_preview()
    return ta
