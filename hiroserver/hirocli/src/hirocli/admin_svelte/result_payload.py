"""How the Svelte admin API answers, and Result→answer mapping.

**Wire contract** (the same as every Hiro app's backend since the UI kit's step 1d, so one frontend client
reads them all):

- **An answer is the data itself** (a JSON object, list, string or null), with HTTP 200.
- **A failure is an HTTP status with FastAPI's body**, ``{"detail": "<words for a person>"}``: 400 unless the
  route says otherwise (401 not signed in, 403 not for this role, 404, 429).
- Routes that serve raw media (``FileResponse``) or raise ``HTTPException`` already answered this way.

Before step 1d every answer was wrapped as ``{"ok", "error", "data"}`` with HTTP 200 even for a failure; that
wrapper is gone (no backward compatibility: the admin frontend moved in the same change).

Use ``api_failure`` for every failure a route returns, so the body stays the same everywhere.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from hirocli.admin.shared.result import Result


def api_failure(error: str, status_code: int = 400) -> JSONResponse:
    """A failure a route returns: an HTTP status and ``{"detail": error}`` (FastAPI's own error body)."""
    return JSONResponse({"detail": error}, status_code=status_code)


def _api_data(result: Result[Any]) -> Any:
    """A service's Result as an answer: its data, or the failure response."""
    if not result.ok:
        return api_failure(result.error or "Operation failed.")
    return result.data


def _api_list(result: Result[Any]) -> Any:
    """A service's Result as a list answer: its rows ([] for none), or the failure response."""
    if not result.ok:
        return api_failure(result.error or "Operation failed.")
    return list(result.data or [])
