"""JSON envelopes and Result→dict mapping for the Svelte admin API.

**Wire contract (stable for consumers — do not change semantics casually):**

- **JSON envelope:** Most admin endpoints return a JSON object with ``ok: bool``, ``error: str | null``,
  and ``data`` (shape varies). Clients should use HTTP status together with ``ok`` as today
  (see ``admin_frontend`` ``apiRequest``).
- **Operational failures:** Domain/service failures are represented inside the envelope with
  ``ok: false`` and a human-readable ``error`` string (via ``_api_from_result``).
- **HTTP-native errors:** Routes that serve raw media (``FileResponse``) or use ``HTTPException``
  follow normal HTTP status codes and bodies — **not** the ``ok/error/data`` envelope.
- **Upload validation:** Invalid photo data URLs return the same envelope with ``ok: false`` (400-class
  semantics are expressed by ``ok``, not necessarily by HTTP status, matching existing handlers).

Use ``envelope_failure`` for manual ``ok: false`` responses so wording stays consistent with
``_api_from_result``.
"""

from __future__ import annotations

from typing import Any

from hirocli.admin.shared.result import Result


def envelope_failure(error: str) -> dict[str, Any]:
    """Canonical ``ok: false`` JSON body (same keys as ``_api_from_result`` on failure)."""
    return {"ok": False, "error": error, "data": None}


def _api_from_result(result: Result[Any]) -> dict[str, Any]:
    if not result.ok:
        return {"ok": False, "error": result.error or "Operation failed.", "data": None}
    return {"ok": True, "error": None, "data": result.data}
