"""Centralized outbound HTTP connection policy for cloud model providers.

Every cloud provider SDK we use (OpenAI, DeepSeek, Google GenAI) talks to its API over an httpx-family
client, and each defaults that client to a ``keepalive_expiry`` of ~5s. Chat turns are
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
    ``http_async_client`` objects. Since openai 3.x these must be **httpx2** clients (the SDK only
    tolerates plain httpx through a deprecated path), so this module builds httpx2 objects.
    httpx2 checks TLS against the OS trust store (no bundled certifi): a host needs system CA
    certificates, or ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` set.
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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

# openai 3.x is built on httpx2; injecting plain httpx clients relies on a deprecated escape hatch.
import httpx2

if TYPE_CHECKING:
    from .preferences import WorkspacePreferences


@dataclass(frozen=True)
class ProviderCallPolicy:
    """How long one cloud model call may wait, and how often it is retried (prefs ``llm.*``).

    One policy for chat, STT and TTS on every cloud provider, so no SDK's own default decides how
    long a user waits: Gemini's was no timeout and 6 attempts, which left a chat turn hanging for
    minutes during a Gemini 503 spell (2026-11-06). Each call site applies it in exactly one retry
    layer (the SDK's, or our tenacity wrapper with the SDK's turned off), never both.
    """

    timeout_s: float = 180.0
    max_retries: int = 2

    @property
    def attempts(self) -> int:
        """Total tries including the first (what google-genai / tenacity count)."""
        return self.max_retries + 1

    @classmethod
    def from_prefs(cls, prefs: WorkspacePreferences) -> ProviderCallPolicy:
        return cls(timeout_s=float(prefs.llm.request_timeout_s), max_retries=int(prefs.llm.max_retries))


def gemini_single_attempt_http_options(policy: ProviderCallPolicy) -> Any:
    """google-genai ``HttpOptions`` for our STT/TTS wrappers: the policy's timeout, one attempt.

    Those wrappers retry with tenacity (``policy.attempts``), so the SDK's own retry is turned off —
    one retry layer, not two. google-genai takes the timeout in milliseconds. Imported lazily: the
    google-genai SDK is optional at import time for this module."""
    from google.genai import types

    return types.HttpOptions(
        timeout=int(policy.timeout_s * 1000),
        retry_options=types.HttpRetryOptions(attempts=1),
    )

# Single source of truth for the connection policy — module-level so a future workspace preference
# can override it in exactly one place.
KEEPALIVE_EXPIRY_S = 300.0
MAX_KEEPALIVE_CONNECTIONS = 10

# Chat: bound the connect (handshake); ``read`` (the wait for the next bytes) comes from the
# workspace's ProviderCallPolicy (``llm.request_timeout_s``) — it was a fixed 600s. httpx2's own
# default is 5s for ALL phases (fatal for chat), so a custom client MUST set it. Fast: a short
# whole-request bound for embeddings / rerank.
_CHAT_CONNECT_S = 15.0
_FAST_TIMEOUT = httpx2.Timeout(30.0)


def _limits(keepalive_s: float | None = None) -> httpx2.Limits:
    # ``keepalive_s`` (workspace pref ``llm.http_keepalive_s``) overrides the module default; a
    # missing / non-positive value falls back so a bad/absent pref never breaks client build.
    expiry = float(keepalive_s) if keepalive_s and keepalive_s > 0 else KEEPALIVE_EXPIRY_S
    return httpx2.Limits(
        max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS,
        keepalive_expiry=expiry,
    )


def _timeout(*, streaming: bool, policy: ProviderCallPolicy | None) -> httpx2.Timeout:
    if not streaming:
        return _FAST_TIMEOUT
    read_s = (policy or ProviderCallPolicy()).timeout_s
    return httpx2.Timeout(connect=_CHAT_CONNECT_S, read=read_s, write=30.0, pool=_CHAT_CONNECT_S)


def openai_http_kwargs(
    *,
    streaming: bool,
    keepalive_s: float | None = None,
    policy: ProviderCallPolicy | None = None,
) -> dict[str, Any]:
    """Warm-keepalive client kwargs for the langchain_openai family (OpenAI, DeepSeek).

    ``streaming`` (chat) also wires ``http_async_client``, since langchain streams over the async
    client; embeddings are sync-only (``embed_documents`` run via ``asyncio.to_thread``) so they
    get just ``http_client`` — no idle async client held for its lifetime. ``keepalive_s`` overrides
    the module-default keepalive window (from the ``llm.http_keepalive_s`` workspace pref);
    ``policy`` sets the chat read timeout (``llm.request_timeout_s``)."""
    limits, timeout = _limits(keepalive_s), _timeout(streaming=streaming, policy=policy)
    kwargs: dict[str, Any] = {"http_client": httpx2.Client(limits=limits, timeout=timeout)}
    if streaming:
        kwargs["http_async_client"] = httpx2.AsyncClient(limits=limits, timeout=timeout)
    return kwargs


__all__ = [
    "KEEPALIVE_EXPIRY_S",
    "MAX_KEEPALIVE_CONNECTIONS",
    "ProviderCallPolicy",
    "openai_http_kwargs",
]
