"""Loading and unloading models on the home's local servers around an AI ask (Part B, ported from HomeHiro's
llm/local.py).

One address per kind (``lm_studio`` / ``ollama``: the credential store's endpoint, else the catalog default),
and one ask at a time per server (the runner's lock: they share the PC's GPU). Before an ask:

- a model the core loaded earlier for another ask on the same server is unloaded first — two rarely fit a
  home GPU (HomeHiro: Qwen3.5 9B + Gemma 4 26B = 25 GB on a 16 GB card);
- **LM Studio**: the model is loaded with the server's settings (context, batch; ``ai.local_servers``) when
  it isn't loaded, or is loaded with less — a model loaded by hand with a small batch crashes on a picture.
  An LM Studio without its REST API (``/api/v1``) loads models by itself on the request (JIT): left alone;
- **Ollama** loads the model with the request itself.

A model the core loaded (LM Studio) or asked (Ollama) is unloaded after the server's ``unload_idle_min``
without an ask (``unload_idle``, run every minute by the AI background job). A model loaded by hand on LM
Studio is left alone.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from hiro_commons.log import Logger

from ...domain.credential_store import CredentialStore
from ...domain.discovered_models import local_server_url
from ...domain.preferences import LocalServerSettings
from .errors import ProviderFailed

log = Logger.get("AI.LOCAL")

LIST_TIMEOUT = 5.0  # seconds: listing models
LOAD_TIMEOUT = 180.0  # loading a big model from disk
_LABELS = {"lm_studio": "LM Studio", "ollama": "Ollama"}


@dataclass(frozen=True)
class _Loaded:
    workspace: str
    provider_id: str
    model: str


# (workspace, kind, model) → loop time of its last ask: what the core loaded and may unload.
_loaded_by_core: dict[_Loaded, float] = {}


def loaded_by_core(workspace_path: Path, provider_id: str) -> dict[str, float]:
    """model → seconds since its last ask, for the models the core loaded on this server."""
    now = time.monotonic()
    return {
        k.model: now - last
        for k, last in _loaded_by_core.items()
        if k.workspace == str(workspace_path) and k.provider_id == provider_id
    }


async def _call(label: str, method: str, url: str, timeout: float, body: dict[str, Any] | None = None) -> Any:
    """The server's JSON answer; ProviderFailed saying what went wrong. Not repeated: a question may be running."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.request(method, url, json=body)
    except httpx.ConnectError as exc:
        raise ProviderFailed(f"{label}: can't connect (is the PC on, and the server running and open to the network?)") from exc
    except httpx.TimeoutException as exc:
        raise ProviderFailed(f"{label}: no answer within {timeout:.0f} s") from exc
    except httpx.HTTPError as exc:
        raise ProviderFailed(f"{label}: {type(exc).__name__}: {exc}") from exc
    if r.status_code == 404:
        raise _NoRestApi(f"{label}: {url} not found")
    if r.status_code >= 400:
        raise ProviderFailed(f"{label}: HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError as exc:
        raise ProviderFailed(f"{label}: an answer Hiro can't read") from exc


class _NoRestApi(ProviderFailed):
    """The server has no such endpoint (an older LM Studio without /api/v1)."""


def _base(workspace_path: Path, provider_id: str, store: CredentialStore | None) -> str:
    url = local_server_url(workspace_path, provider_id, store=store)
    if not url:
        raise ProviderFailed(f"{_LABELS.get(provider_id, provider_id)} has no address set")
    return url[: -len("/v1")] if url.endswith("/v1") else url


async def prepare(
    workspace_path: Path,
    provider_id: str,
    model: str,
    settings: LocalServerSettings,
    *,
    context: int | None,
    store: CredentialStore | None,
) -> None:
    """Make room and load ``model`` before an ask (module notes). Call under the server's lock."""
    label = _LABELS.get(provider_id, provider_id)
    base = _base(workspace_path, provider_id, store)
    for other in [m for m in loaded_by_core(workspace_path, provider_id) if m != model]:
        try:
            await unload(provider_id, base, other)
            log.info(f"⬆️ Local model unloaded to make room — {label} · {other} → {model}")
        except ProviderFailed as exc:  # already gone (unloaded by hand): nothing to make room for
            log.warning(f"⚠️ Couldn't unload a local model — {label} · {other}", error=str(exc))
        _loaded_by_core.pop(_Loaded(str(workspace_path), provider_id, other), None)
    key = _Loaded(str(workspace_path), provider_id, model)
    if provider_id == "ollama":
        _loaded_by_core[key] = time.monotonic()  # the ask loads it; the idle job unloads it
        return
    if provider_id == "lm_studio" and await _lm_studio_ensure(label, base, model, context or settings.context, settings.batch):
        _loaded_by_core[key] = time.monotonic()


def asked(workspace_path: Path, provider_id: str, model: str) -> None:
    """An ask on ``model`` ended: its idle time starts again."""
    key = _Loaded(str(workspace_path), provider_id, model)
    if key in _loaded_by_core:
        _loaded_by_core[key] = time.monotonic()


async def _lm_studio_ensure(label: str, base: str, model: str, context: int, batch: int) -> bool:
    """Have ``model`` loaded with at least ``context`` / ``batch``; whether this loaded it."""
    try:
        data = await _call(label, "GET", f"{base}/api/v1/models", LIST_TIMEOUT)
    except _NoRestApi:
        return False  # no REST API: LM Studio loads the model itself on the request
    found = next((m for m in data.get("models") or [] if m.get("key") == model), None)
    if found is None:
        raise ProviderFailed(f"{label} has no model {model}")
    instances = [(i.get("id"), i.get("config") or {}) for i in found.get("loaded_instances") or []]
    if any(
        (c.get("context_length") or 0) >= context and (c.get("physical_batch_size") or 0) >= batch for _, c in instances
    ):
        return False
    for instance, c in instances:  # loaded with less than a picture needs: load it again with ours
        log.warning(
            f"⚠️ Local model loaded with too little — {label} · {model}; loading it again",
            context=c.get("context_length"),
            batch=c.get("physical_batch_size"),
        )
        await _call(label, "POST", f"{base}/api/v1/models/unload", LIST_TIMEOUT, {"instance_id": instance})
    started = time.monotonic()
    await _call(
        label,
        "POST",
        f"{base}/api/v1/models/load",
        LOAD_TIMEOUT,
        {
            "model": model,
            "context_length": context,
            "eval_batch_size": batch,
            "physical_batch_size": batch,
            "parallel": 1,
            "flash_attention": True,
        },
    )
    log.info(
        f"✅ Local model loaded — {label} · {model}",
        elapsed_ms=int((time.monotonic() - started) * 1000),
        context=context,
        batch=batch,
    )
    return True


async def unload(provider_id: str, base: str, model: str) -> None:
    label = _LABELS.get(provider_id, provider_id)
    if provider_id == "ollama":
        await _call(label, "POST", f"{base}/api/generate", LIST_TIMEOUT, {"model": model, "keep_alive": 0})
    else:
        await _call(label, "POST", f"{base}/api/v1/models/unload", LIST_TIMEOUT, {"instance_id": model})


async def unload_idle(
    workspace_path: Path,
    settings_for: dict[str, LocalServerSettings],
    busy: set[str],
    store: CredentialStore | None,
) -> list[str]:
    """Unload what the core loaded once idle for its server's minutes; ``busy``: servers mid-ask (skipped)."""
    done: list[str] = []
    now = time.monotonic()
    for key, last in list(_loaded_by_core.items()):
        if key.workspace != str(workspace_path) or key.provider_id in busy:
            continue
        minutes = (settings_for.get(key.provider_id) or LocalServerSettings()).unload_idle_min
        if now - last < minutes * 60:
            continue
        label = _LABELS.get(key.provider_id, key.provider_id)
        try:
            await unload(key.provider_id, _base(workspace_path, key.provider_id, store), key.model)
            log.info(f"⬆️ Local model unloaded after {minutes} min without an ask — {label} · {key.model}")
            done.append(f"{key.provider_id}:{key.model}")
        except ProviderFailed as exc:  # the PC is off or the model is gone: nothing left to unload
            log.warning(f"⚠️ Couldn't unload an idle local model — {label} · {key.model}", error=str(exc))
        _loaded_by_core.pop(key, None)
    return done


def forget_all() -> None:
    """Tests: nothing loaded by the core."""
    _loaded_by_core.clear()


async def run_unload_idle(workspace_path: Path, settings_for: dict[str, LocalServerSettings], locks: dict[str, asyncio.Lock], store: CredentialStore | None) -> list[str]:
    """``unload_idle`` with the runner's per-server locks deciding which servers are mid-ask."""
    busy = {pid for pid, lock in locks.items() if lock.locked()}
    return await unload_idle(workspace_path, settings_for, busy, store)
