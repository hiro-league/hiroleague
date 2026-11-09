"""HTTP calls to the speech providers (Phase 7b, ported from HomeHiro's ``core/http.py``).

A paid call is never sent twice:

- a request that never reached the provider (no connection) is sent again;
- 429 (too many requests: nothing was done) is sent again after a wait;
- GET, HEAD and DELETE are also sent again after other network errors and 5xx;
- a POST that may have reached the provider (no answer in time, a dropped connection, a 5xx) is not:
  it may have been done, and billed, already. The error says so.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from hiro_commons.log import Logger

log = Logger.get("VOICE")

ATTEMPTS = 3
NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)  # nothing reached the provider
REPEATABLE = ("GET", "HEAD", "DELETE")


class VoiceError(Exception):
    """A problem worth showing as is. ``status``: 400 for our side (bad input, no key), 404 for something
    that isn't there, 502 for the provider's."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


async def send(method: str, url: str, *, provider: str, timeout: float = 90, **kwargs: Any) -> httpx.Response:
    """The provider's answer (below 400), or VoiceError saying what went wrong (module notes)."""
    repeatable = method.upper() in REPEATABLE
    what = f"{provider}: {method.upper()} {httpx.URL(url).path}"  # the path only: a query may hold a key
    for attempt in range(1, ATTEMPTS + 1):
        last = attempt == ATTEMPTS
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:  # timeouts and dropped connections too
            sent = not isinstance(exc, NOT_SENT)
            if sent and not repeatable:
                raise VoiceError(
                    f"{provider}: no answer ({type(exc).__name__}); not asked again, as it may have been done "
                    "(and billed) already"
                ) from exc
            if last:
                raise VoiceError(f"{provider}: could not reach the API ({type(exc).__name__})") from exc
            log.warning(f"⚠️ {what} — {type(exc).__name__}, trying again")
        except httpx.HTTPError as exc:  # not the connection: a body that doesn't decode, too many redirects
            raise VoiceError(f"{provider}: {type(exc).__name__}: {exc}") from exc
        else:
            if r.status_code < 400:
                log.debug(f"⬆️ {what} — {r.status_code}", elapsed_ms=int((time.monotonic() - started) * 1000))
                return r
            again = r.status_code == 429 or (repeatable and r.status_code >= 500)
            if not again or last:
                raise VoiceError(f"{provider}: {_error_message(r)}", 404 if r.status_code == 404 else 502)
            log.warning(f"⚠️ {what} — HTTP {r.status_code}, trying again")
        await asyncio.sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")


def _error_message(r: httpx.Response) -> str:
    try:
        err = r.json().get("error")
        message = err.get("message") if isinstance(err, dict) else err
    except (ValueError, AttributeError):
        message = None
    return str(message or f"HTTP {r.status_code}").strip()
