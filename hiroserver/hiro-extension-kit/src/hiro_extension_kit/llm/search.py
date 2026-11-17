"""Searching with the core's models: vectors (`ai.embed`), an order (`ai.rerank`) and chat's memory settings
(`memory.settings`), so an app (EvalHiro) searches the way Hiro's memory does instead of keeping its own models and keys.

The app declares its uses (`Extension.embed_uses`, `Extension.rerank_uses`); the core's admin points each at an
embedding or a reranker profile (Catalog → Profiles → Uses). A call names the use (the app's first declared one when it
names none), or a profile of the core's directly.

Errors callers handle: `Unavailable` (503) when the app isn't connected to the core or no profile is picked for the use,
`Invalid` (400) when the core refused the request itself, `LLMError` (502) when the model failed or didn't answer in time.
"""

from dataclasses import dataclass
from typing import Any

from hiro_channel_sdk import ExtensionRequestError
from hiro_channel_sdk.constants import METHOD_AI_EMBED, METHOD_AI_RERANK, METHOD_MEMORY_SETTINGS

from .. import calls, identity
from ..errors import Invalid, Unavailable
from ..extension import ext
from ..hiroleague import link
from . import LLMError

log = identity.logger("llm")

TIMEOUT = 120.0  # seconds: a local model the core loads for the first time takes a while
SETTINGS_TIMEOUT = 10.0
WHERE = "HiroLeague's admin (Catalog → Profiles → Uses)"


@dataclass(frozen=True)
class Embedded:
    """The vectors, one per text in order, and the profile that made them (a graph keeps its embedder)."""

    vectors: list[list[float]]
    dimensions: int
    model: str
    profile_id: str
    profile_name: str
    ms: int


@dataclass(frozen=True)
class Ranked:
    """One document of a rerank: its index in the documents sent, and the model's score in [0, 1] (None: no score)."""

    index: int
    score: float | None


@dataclass(frozen=True)
class Reranked:
    results: list[Ranked]  # best first
    model: str
    profile_id: str
    profile_name: str
    ms: int


def _no_core() -> str:
    return f"{identity.app().title} isn't connected to HiroLeague (Settings → HiroLeague)"


def _use(given: str | None, declared: Any, what: str) -> str:
    if given:
        return given
    if declared:
        return declared[0].id
    raise Invalid(f"{identity.app().title} declares no {what} use")


def _refused(exc: ExtensionRequestError, use: str, what: str) -> Exception:
    """The core's refusal as the error callers handle."""
    if exc.code == "not_connected":
        return Unavailable(_no_core())
    if exc.code == "no_profile":
        return Unavailable(f"No {what} profile for '{use}': pick one in {WHERE}. ({exc.message})")
    if exc.code == "invalid":
        return Invalid(f"HiroLeague refused the {what} request: {exc.message}")
    if exc.code == "timeout":
        return LLMError(f"HiroLeague didn't {what} in {TIMEOUT:.0f} s")
    return LLMError(f"HiroLeague couldn't {what}: {exc.message}")


async def _request(method: str, params: dict[str, Any], use: str, what: str, timeout: float) -> dict[str, Any]:
    if not link.client.connected:
        raise Unavailable(_no_core())
    started = calls.start()
    try:
        answer = await link.client.request(method, params, timeout=timeout)
    except ExtensionRequestError as exc:
        raise _refused(exc, use, what) from exc
    calls.done(log, f"HiroLeague: {method} ({use})", started, timeout=timeout, paid=True)
    if not isinstance(answer, dict):
        raise LLMError(f"HiroLeague's {what} answer can't be read")
    return answer


async def embed(texts: list[str], *, use: str | None = None, profile: str | None = None) -> Embedded:
    """Vectors for `texts` with the core's embedding profile for `use` (or `profile`)."""
    name = _use(use, ext().embed_uses, "embed") if not profile or use else ""
    params: dict[str, Any] = {"texts": list(texts)}
    if name:
        params["use"] = name
    if profile:
        params["profile"] = profile
    a = await _request(METHOD_AI_EMBED, params, name or profile or "", "embed", TIMEOUT)
    try:
        vectors = [[float(x) for x in v] for v in a["vectors"]]
        return Embedded(vectors=vectors, dimensions=int(a.get("dimensions") or (len(vectors[0]) if vectors else 0)),
                        model=str(a.get("model") or ""), profile_id=str(a.get("profile_id") or ""),
                        profile_name=str(a.get("profile_name") or ""), ms=int(a.get("ms") or 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise LLMError(f"HiroLeague's vectors can't be read ({type(exc).__name__})") from exc


async def rerank(
    query: str, documents: list[str], *, top_n: int | None = None, use: str | None = None, profile: str | None = None
) -> Reranked:
    """`documents` in order of relevance to `query`, best first, with the core's reranker profile for `use`."""
    name = _use(use, ext().rerank_uses, "rerank") if not profile or use else ""
    params: dict[str, Any] = {"query": query, "documents": list(documents)}
    if name:
        params["use"] = name
    if profile:
        params["profile"] = profile
    if top_n is not None:
        params["top_n"] = top_n
    a = await _request(METHOD_AI_RERANK, params, name or profile or "", "rerank", TIMEOUT)
    try:
        results = [Ranked(index=int(r["index"]), score=None if r.get("score") is None else float(r["score"]))
                   for r in a["results"]]
        return Reranked(results=results, model=str(a.get("model") or ""), profile_id=str(a.get("profile_id") or ""),
                        profile_name=str(a.get("profile_name") or ""), ms=int(a.get("ms") or 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise LLMError(f"HiroLeague's order can't be read ({type(exc).__name__})") from exc


async def memory_settings() -> dict[str, Any]:
    """Chat's memory settings as the core runs them: {memory, graph, embedder, reranker} (`memory.settings`)."""
    return await _request(METHOD_MEMORY_SETTINGS, {}, "memory settings", "read memory settings", SETTINGS_TIMEOUT)


__all__ = ["Embedded", "Ranked", "Reranked", "embed", "memory_settings", "rerank"]
