"""NiceGUI APIRouter for HiroAdmin — routes at site root on the shared core.app.

HiroAdmin owns `/`, `/workspaces`, etc. Legacy `hirocli.ui` pages are not registered
on startup; their package remains in the repo for reference only.
"""

from __future__ import annotations

from nicegui import APIRouter

# Home URL for nav + active_path (NiceGUI treats `/` as the dashboard).
ADMIN_ROOT = "/"

admin_router = APIRouter(prefix="")
