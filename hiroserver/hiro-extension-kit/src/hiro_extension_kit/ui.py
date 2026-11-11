"""The app's built SvelteKit UI (frontend/build), for every path that isn't the API. In the container it is
copied to /app/static; in dev the UI is served by Vite instead, so a missing folder is fine.

How long a browser may keep each file (Cache-Control): the build's files under _app/immutable/ have their content's
hash in their name, so a browser keeps them for a year; everything else (the pages, version.json, icons) keeps its
name across builds, so a browser must ask again each time. Without the header a browser guesses (10% of the time
since the file changed): after a deploy it could show the old app for an hour or more (seen 2026-10-04)."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import identity
from .errors import NotFound

STATIC_DIR = identity.app().static_dir
router = APIRouter()
IMMUTABLE = "_app/immutable/"


def cache_control(path: str) -> str:
    """The Cache-Control for a built file: a year for hashed files, else ask again each time."""
    return "public, max-age=31536000, immutable" if path.startswith(IMMUTABLE) else "no-cache"


@router.get("/{path:path}", include_in_schema=False)
def ui(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(404)
    # Real files (JS, CSS, icons), then prerendered pages ("" -> index.html, "reports" -> reports.html),
    # then the SPA fallback for routes that were not prerendered.
    for candidate in (path, f"{path}.html" if path else "index.html", "200.html"):
        try:
            file = (STATIC_DIR / candidate).resolve()
        except (ValueError, OSError):  # a name no file can have (a null byte, one Windows refuses): not a file
            continue
        if file.is_file() and file.is_relative_to(STATIC_DIR):
            return FileResponse(file, headers={"Cache-Control": cache_control(candidate)})
    raise NotFound("UI not built; in dev open the Vite server on :5173")
