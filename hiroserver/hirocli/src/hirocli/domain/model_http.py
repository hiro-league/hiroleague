"""Centralized outbound HTTP connection policy for cloud model providers.

Every cloud provider SDK we use (OpenAI, DeepSeek, Google GenAI) talks to its API over an httpx
client, and each defaults that client to httpx's ``keepalive_expiry`` of ~5s. Chat turns are
human-paced (far more than 5s apart), so the pool's idle socket is dead by the next turn and the
first call to a provider re-pays a full DNS+TCP+TLS handshake — ~1.7s was observed on a single
graph query-embed, independent of record count. This module is the **single source of truth** for
the connection policy so it is applied once and consistently instead of scattered per provider
branch in ``model_factory``.

What actually moves the needle is the pool ``limits`` (``keepalive_expiry`` /
``max_keepalive_connections``): they live on the httpx connection pool and are NOT overridden per
request, so they hold for every provider we inject them into (verified: the values reach the pool
for both the OpenAI-family and Google clients). The real ceiling on cross-turn warmth is each
provider's *server-side* idle timeout (~60-240s), so a huge value buys nothing past that — 300s
just spans normal turn spacing.

Injection differs by SDK (verified against the installed client classes):
  - OpenAI / DeepSeek (langchain_openai family) take explicit ``http_client`` /
    ``http_async_client`` objects — both httpx, so this is clean.
Providers left on their SDK defaults (no safe hook):
  - Google GenAI — its ASYNC path uses aiohttp (not httpx) with a hardcoded connector, and it
    forwards ``client_args`` straight into ``aiohttp.ClientSession.request(**args)`` alongside its
    own ``timeout=`` — so any httpx-shaped kwarg (``limits`` / ``timeout``) collides there
    ("got multiple values for keyword argument 'timeout'"). No cross-transport keepalive hook.
  - Anthropic, Cohere, Voyage — expose only a pre-built client object, no httpx hook.
  - Ollama, LM Studio — local endpoints, keepalive to localhost is pointless.

A fresh client is built per model construction; models are cached / long-lived (the agent compile
cache, the recall-model cache, the memory-service embedder), so this is a one-time cost per model,
not per call.
"""

from __future__ import annotations

from typing import Any

import httpx

# Single source of truth for the connection policy — module-level so a future workspace preference
# can override it in exactly one place.
KEEPALIVE_EXPIRY_S = 300.0
MAX_KEEPALIVE_CONNECTIONS = 10

# Chat: bound the connect (handshake) but keep ``read`` generous so long / reasoning generations
# are never cut off mid-stream (httpx's own default is 5s for ALL phases — fatal for chat — so a
# custom client MUST set this). Fast: a short whole-request bound for embeddings / rerank.
_CHAT_TIMEOUT = httpx.Timeout(connect=15.0, read=600.0, write=30.0, pool=15.0)
_FAST_TIMEOUT = httpx.Timeout(30.0)


def _limits(keepalive_s: float | None = None) -> httpx.Limits:
    # ``keepalive_s`` (workspace pref ``llm.http_keepalive_s``) overrides the module default; a
    # missing / non-positive value falls back so a bad/absent pref never breaks client build.
    expiry = float(keepalive_s) if keepalive_s and keepalive_s > 0 else KEEPALIVE_EXPIRY_S
    return httpx.Limits(
        max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS,
        keepalive_expiry=expiry,
    )


def _timeout(*, streaming: bool) -> httpx.Timeout:
    return _CHAT_TIMEOUT if streaming else _FAST_TIMEOUT


def openai_http_kwargs(*, streaming: bool, keepalive_s: float | None = None) -> dict[str, Any]:
    """Warm-keepalive client kwargs for the langchain_openai family (OpenAI, DeepSeek).

    ``streaming`` (chat) also wires ``http_async_client``, since langchain streams over the async
    client; embeddings are sync-only (``embed_documents`` run via ``asyncio.to_thread``) so they
    get just ``http_client`` — no idle async client held for its lifetime. ``keepalive_s`` overrides
    the module-default keepalive window (from the ``llm.http_keepalive_s`` workspace pref)."""
    limits, timeout = _limits(keepalive_s), _timeout(streaming=streaming)
    kwargs: dict[str, Any] = {"http_client": httpx.Client(limits=limits, timeout=timeout)}
    if streaming:
        kwargs["http_async_client"] = httpx.AsyncClient(limits=limits, timeout=timeout)
    return kwargs


__all__ = [
    "KEEPALIVE_EXPIRY_S",
    "MAX_KEEPALIVE_CONNECTIONS",
    "openai_http_kwargs",
]
