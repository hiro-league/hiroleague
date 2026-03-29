"""Feature-scoped head assets for Characters admin (guidelines §3.3)."""

from __future__ import annotations

from nicegui import ui

# Pinned CDN versions for reproducible crop UI (admin-local only).
_CROPPER_CSS = "https://cdn.jsdelivr.net/npm/cropperjs@1.6.2/dist/cropper.min.css"
_CROPPER_JS = "https://cdn.jsdelivr.net/npm/cropperjs@1.6.2/dist/cropper.min.js"

_styles_registered = False


def register_character_admin_styles() -> None:
    """Load Cropper.js once for the admin app (idempotent; guidelines §3.3)."""
    global _styles_registered
    if _styles_registered:
        return
    ui.add_head_html(
        f'<link rel="stylesheet" href="{_CROPPER_CSS}" crossorigin="anonymous" />\n'
        f'<script src="{_CROPPER_JS}" crossorigin="anonymous"></script>',
        shared=True,
    )
    _styles_registered = True
