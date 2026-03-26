"""NiceGUI APIRouter for HiroAdmin v2 — isolated paths under /v2/ on the shared core.app.

NiceGUI keeps a single global `core.app`; a second `ui.run_with()` still mounts that same
app, so duplicate @ui.page('/') handlers overwrite the legacy UI. V2 routes must use a
path prefix so they coexist with legacy routes on one admin port.
"""

from __future__ import annotations

from nicegui import APIRouter

# Browser paths: /v2/, /v2/workspaces, …
V2_PREFIX = "/v2"
V2_ROOT = f"{V2_PREFIX}/"

v2_router = APIRouter(prefix=V2_PREFIX)
