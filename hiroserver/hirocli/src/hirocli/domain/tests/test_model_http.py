"""Tests for the centralized provider HTTP connection policy (model_http)."""

from __future__ import annotations

import httpx

from hirocli.domain.model_http import (
    KEEPALIVE_EXPIRY_S,
    MAX_KEEPALIVE_CONNECTIONS,
    google_http_kwargs,
    openai_http_kwargs,
)


def _pool_keepalive(client: httpx.Client | httpx.AsyncClient) -> float:
    """Read the keepalive_expiry off the client's httpcore connection pool."""
    return client._transport._pool._keepalive_expiry


def test_openai_streaming_wires_sync_and_async_clients_with_keepalive() -> None:
    kwargs = openai_http_kwargs(streaming=True)
    assert set(kwargs) == {"http_client", "http_async_client"}
    assert isinstance(kwargs["http_client"], httpx.Client)
    assert isinstance(kwargs["http_async_client"], httpx.AsyncClient)
    # The pool keepalive (the actual fix — not overridden per request) carries our policy.
    assert _pool_keepalive(kwargs["http_client"]) == KEEPALIVE_EXPIRY_S
    assert _pool_keepalive(kwargs["http_async_client"]) == KEEPALIVE_EXPIRY_S
    # Chat keeps a generous read so long / reasoning generations aren't cut off mid-stream.
    assert kwargs["http_client"].timeout.read == 600.0


def test_openai_non_streaming_is_sync_only() -> None:
    # Embeddings are sync (embed_documents via asyncio.to_thread) — no idle async client is held.
    kwargs = openai_http_kwargs(streaming=False)
    assert set(kwargs) == {"http_client"}
    assert _pool_keepalive(kwargs["http_client"]) == KEEPALIVE_EXPIRY_S
    # Fast profile: short whole-request bound for the quick embed call.
    assert kwargs["http_client"].timeout.read == 30.0


def test_google_kwargs_carry_limits_and_timeout() -> None:
    # google-genai takes raw httpx kwargs via client_args (it forwards them to its httpx.Client).
    for streaming, read in ((True, 600.0), (False, 30.0)):
        kwargs = google_http_kwargs(streaming=streaming)
        assert set(kwargs) == {"client_args"}
        client_args = kwargs["client_args"]
        assert set(client_args) == {"limits", "timeout"}
        assert client_args["limits"].keepalive_expiry == KEEPALIVE_EXPIRY_S
        assert client_args["limits"].max_keepalive_connections == MAX_KEEPALIVE_CONNECTIONS
        assert client_args["timeout"].read == read


def test_keepalive_override_and_fallback() -> None:
    # The workspace pref (llm.http_keepalive_s) overrides the module default...
    assert _pool_keepalive(openai_http_kwargs(streaming=False, keepalive_s=45.0)["http_client"]) == 45.0
    assert google_http_kwargs(streaming=True, keepalive_s=45.0)["client_args"][
        "limits"
    ].keepalive_expiry == 45.0
    # ...but a missing / non-positive value falls back to the default (never breaks client build).
    for bad in (None, 0, -1):
        assert (
            _pool_keepalive(openai_http_kwargs(streaming=False, keepalive_s=bad)["http_client"])
            == KEEPALIVE_EXPIRY_S
        )


def test_each_call_builds_a_fresh_client() -> None:
    # Clients must not be shared across model instances (an async client is loop-bound, and closing
    # one would break another); each build gets its own.
    assert openai_http_kwargs(streaming=True)["http_client"] is not (
        openai_http_kwargs(streaming=True)["http_client"]
    )
