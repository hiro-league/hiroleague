"""Models a local server reports (LM Studio / Ollama), offered without catalog rows (Phase 7a).

A local server runs whatever models its owner pulled, so the catalog can't list them all. An AI
profile may point at any of them as ``lm_studio:<name>`` / ``ollama:<name>``: the server is asked
for its models (``probe_local_models``), and the answer is kept in workspace.db's ``local_models``
table (``save_discovered_models``) so profiles still read, and the admin still lists them, while
the PC is off. Catalog rows for local models keep working as before; a discovered model with no
catalog row gets a synthetic ``ModelSpec`` (``discovered_model_spec``) so ``model_factory`` can
build it.

Each local kind keeps one address (the credential store's endpoint, else the catalog default).
Loading and unloading idle models (HomeHiro's ``llm/local.py``) is Phase 7a Part B.

As HomeHiro tested them (2026-10-01): LM Studio's ``GET /api/v1/models`` says per model whether
it sees pictures and whether it is loaded; Ollama's ``GET /api/tags`` lists the models and
``POST /api/show`` their capabilities (``completion``, ``vision``, ``thinking``).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from hiro_commons.timestamps import utc_iso

from .credential_store import CredentialStore
from .db import db_path, ensure_db
from .model_catalog import ModelSpec, get_model_catalog

logger = logging.getLogger(__name__)

# Local kinds whose models are discovered from the server (one address each).
DISCOVERABLE_LOCAL_PROVIDERS: tuple[str, ...] = ("lm_studio", "ollama")
LIST_TIMEOUT_S = 5.0


class LocalServerError(RuntimeError):
    """The local server couldn't be asked for its models (off, wrong address, odd answer)."""


@dataclass(frozen=True)
class DiscoveredModel:
    provider_id: str
    name: str  # as the server names it (the part after "provider:")
    display_name: str
    vision: bool
    reasoning: bool
    loaded: bool
    seen_at: str = ""

    @property
    def id(self) -> str:
        return f"{self.provider_id}:{self.name}"


def local_server_url(
    workspace_path: Path,
    provider_id: str,
    *,
    store: CredentialStore | None = None,
    workspace_id: str | None = None,
) -> str | None:
    """The address kept for a local kind: its stored endpoint, else the catalog default."""
    cred = None
    if store is not None:
        cred = store.get(provider_id)
    elif workspace_id is not None:
        cred = CredentialStore(workspace_path, workspace_id).get(provider_id)
    if cred is not None and cred.base_url:
        return cred.base_url.rstrip("/")
    prov = get_model_catalog().get_provider(provider_id)
    return prov.default_base_url.rstrip("/") if prov and prov.default_base_url else None


# ---------------------------------------------------------------------------
# Asking the server
# ---------------------------------------------------------------------------


def probe_local_models(provider_id: str, base_url: str) -> list[DiscoveredModel]:
    """The chat models the server has now. Raises LocalServerError when it can't say."""
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    try:
        if provider_id == "ollama":
            return _ollama_models(base)
        if provider_id == "lm_studio":
            return _lm_studio_models(base)
    except httpx.ConnectError as exc:
        raise LocalServerError(f"can't connect to {base} (is the server running?)") from exc
    except httpx.TimeoutException as exc:
        raise LocalServerError(f"no answer from {base} within {LIST_TIMEOUT_S:.0f} s") from exc
    except httpx.HTTPError as exc:
        raise LocalServerError(f"{base}: {type(exc).__name__}: {exc}") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise LocalServerError(f"{base}: a model list Hiro can't read ({exc})") from exc
    raise LocalServerError(f"{provider_id!r} isn't a local server kind Hiro can list")


def _get_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    resp = httpx.request(method, url, json=body, timeout=LIST_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def _ollama_models(base: str) -> list[DiscoveredModel]:
    tags = _get_json(f"{base}/api/tags")
    try:
        running = {m.get("name") for m in (_get_json(f"{base}/api/ps").get("models") or [])}
    except httpx.HTTPError:
        running = set()  # older Ollama without /api/ps: "loaded" is just unknown
    out: list[DiscoveredModel] = []
    for m in tags.get("models") or []:
        name = m.get("name")
        if not isinstance(name, str) or not name:
            continue
        shown = _get_json(f"{base}/api/show", method="POST", body={"model": name})
        caps = shown.get("capabilities") or []
        if "completion" not in caps:  # an embedding model
            continue
        out.append(
            DiscoveredModel(
                provider_id="ollama",
                name=name,
                display_name=name,
                vision="vision" in caps,
                reasoning="thinking" in caps,
                loaded=name in running,
            )
        )
    return out


def _lm_studio_models(base: str) -> list[DiscoveredModel]:
    try:
        data = _get_json(f"{base}/api/v1/models")
    except httpx.HTTPStatusError:
        return _openai_compatible_models("lm_studio", base)  # an LM Studio without the REST API
    out: list[DiscoveredModel] = []
    for m in data.get("models") or []:
        if m.get("type") != "llm":
            continue
        key = m.get("key")
        if not isinstance(key, str) or not key:
            continue
        caps = m.get("capabilities") or {}
        out.append(
            DiscoveredModel(
                provider_id="lm_studio",
                name=key,
                display_name=str(m.get("display_name") or key),
                vision=bool(caps.get("vision")),
                reasoning=bool(caps.get("reasoning")),
                loaded=bool(m.get("loaded_instances")),
            )
        )
    return out


def _openai_compatible_models(provider_id: str, base: str) -> list[DiscoveredModel]:
    data = _get_json(f"{base}/v1/models")
    return [
        DiscoveredModel(provider_id=provider_id, name=m["id"], display_name=m["id"], vision=False, reasoning=False, loaded=False)
        for m in data.get("data") or []
        if isinstance(m.get("id"), str) and m["id"]
    ]


# ---------------------------------------------------------------------------
# What was last seen — workspace.db local_models
# ---------------------------------------------------------------------------


def save_discovered_models(workspace_path: Path, provider_id: str, models: list[DiscoveredModel]) -> None:
    """Replace the kept list for ``provider_id`` with what the server reported now."""
    ensure_db(workspace_path)
    now = utc_iso(datetime.now(UTC))
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute("DELETE FROM local_models WHERE provider_id = ?", (provider_id,))
        conn.executemany(
            "INSERT INTO local_models (provider_id, name, display_name, vision, reasoning, loaded, seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(provider_id, m.name, m.display_name, int(m.vision), int(m.reasoning), int(m.loaded), now) for m in models],
        )
        conn.commit()


def list_discovered_models(workspace_path: Path, provider_id: str | None = None) -> list[DiscoveredModel]:
    ensure_db(workspace_path)
    query = "SELECT provider_id, name, display_name, vision, reasoning, loaded, seen_at FROM local_models"
    args: tuple[Any, ...] = ()
    if provider_id is not None:
        query += " WHERE provider_id = ?"
        args = (provider_id,)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        rows = conn.execute(query + " ORDER BY provider_id, name", args).fetchall()
    return [
        DiscoveredModel(
            provider_id=r[0],
            name=r[1],
            display_name=r[2] or r[1],
            vision=bool(r[3]),
            reasoning=bool(r[4]),
            loaded=bool(r[5]),
            seen_at=r[6] or "",
        )
        for r in rows
    ]


def get_discovered_model(workspace_path: Path, model_id: str) -> DiscoveredModel | None:
    provider_id, _, name = model_id.partition(":")
    for m in list_discovered_models(workspace_path, provider_id):
        if m.name == name:
            return m
    return None


def discovered_model_spec(model: DiscoveredModel) -> ModelSpec:
    """A catalog-shaped row for a discovered model, so model_factory can build it."""
    features = ["structured_output", "json_mode"]
    if model.reasoning:
        features.append("reasoning")
    return ModelSpec(
        id=model.id,
        provider_id=model.provider_id,
        display_name=model.display_name,
        model_kind="chat",
        modalities=["text", "image"] if model.vision else ["text"],
        features=features,
        tags=["local", "discovered"],
    )
