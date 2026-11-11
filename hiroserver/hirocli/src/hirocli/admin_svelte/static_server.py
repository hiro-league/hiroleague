"""FastAPI mounting helper for the Svelte-based Hiro Admin."""

from __future__ import annotations

import stat
from importlib.resources import files
from pathlib import Path

import anyio
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import URL
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

ADMIN_PATH = "/"


class AdminStaticFiles(StaticFiles):
    """The built admin, with pages that have no trailing slash (UI kit step 1d).

    The build writes a page as ``server.html`` and its address is ``/server``. Starlette's
    ``StaticFiles`` only knows ``<dir>/index.html``, so a hard reload on a page would be a 404;
    this serves ``<path>.html`` for a path with no file. The old address ``/server/`` is sent on
    to ``/server`` (the query is kept), the way Starlette sends a directory on to its slash.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or scope["method"] not in ("GET", "HEAD"):
                raise
            try:
                full_path, stat_result = await anyio.to_thread.run_sync(self.lookup_path, f"{path}.html")
            except (OSError, ValueError):
                raise exc from None
            if stat_result is None or not stat.S_ISREG(stat_result.st_mode):
                raise exc from None
            if scope["path"].endswith("/"):
                url = URL(scope=scope)
                return RedirectResponse(url=url.replace(path=url.path.rstrip("/")))
            return self.file_response(full_path, stat_result, scope)


def admin_svelte_static_dir() -> Path:
    """Return the installed static asset directory for Hiro Admin."""
    return Path(files("hirocli.admin_svelte").joinpath("static"))


def mount_admin_svelte_static(
    app: FastAPI,
    *,
    path: str = ADMIN_PATH,
    require_built: bool = True,
) -> bool:
    """Mount the built Svelte app on *app*.

    Build assets first with ``npm --prefix admin_frontend run package:python``.
    """
    static_dir = admin_svelte_static_dir()
    index_file = static_dir / "index.html"
    if not index_file.exists():
        if not require_built:
            return False
        raise RuntimeError(
            "Hiro Admin static assets are missing. Run "
            "`npm --prefix admin_frontend run package:python` first."
        )

    normalized = "/" + path.strip("/")
    if normalized != "/":

        @app.get(normalized, include_in_schema=False)
        async def _admin_redirect() -> RedirectResponse:
            return RedirectResponse(f"{normalized}/")

    app.mount(
        normalized,
        AdminStaticFiles(directory=static_dir, html=True),
        name="hiro-admin",
    )
    return True
