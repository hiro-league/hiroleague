"""Optional FastAPI mounting helper for the Svelte-based HiroAdmin POC.

This module is intentionally not imported by the existing NiceGUI admin bootstrap.
It exists so the POC has a clear packaging and serving boundary without changing
the current admin UI.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

ADMIN_NEXT_PATH = "/admin-next"


def admin_svelte_static_dir() -> Path:
    """Return the installed static asset directory for HiroAdmin Next."""
    return Path(files("hirocli.admin_svelte").joinpath("static"))


def mount_admin_svelte_static(
    app: FastAPI,
    *,
    path: str = ADMIN_NEXT_PATH,
    require_built: bool = True,
) -> bool:
    """Mount the built Svelte app on *app*.

    Build assets first with ``npm --prefix admin_frontend run package:python``.
    The existing NiceGUI admin does not call this helper yet.
    """
    static_dir = admin_svelte_static_dir()
    index_file = static_dir / "index.html"
    if not index_file.exists():
        if not require_built:
            return False
        raise RuntimeError(
            "HiroAdmin Next static assets are missing. Run "
            "`npm --prefix admin_frontend run package:python` first."
        )

    normalized = "/" + path.strip("/")

    @app.get(normalized, include_in_schema=False)
    async def _admin_next_redirect() -> RedirectResponse:
        return RedirectResponse(f"{normalized}/")

    app.mount(
        normalized,
        StaticFiles(directory=static_dir, html=True),
        name="hiro-admin-next",
    )
    return True
