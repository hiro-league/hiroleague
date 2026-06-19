"""Provider credentials and workspace-available LLM tools (Phase 2a)."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
from hiro_commons.log import Logger

from ..domain.available_models import AvailableModelsService
from ..domain.credential_store import CredentialStore
from ..domain.model_catalog import MODEL_KINDS, ModelKind, get_model_catalog
from ..domain.workspace import WorkspaceError, resolve_workspace
from .base import Tool, ToolParam

log = Logger.get("TOOL.PROVIDER")

# Local endpoint probes must fail fast — a down/unreachable server should report "offline"
# in a couple of seconds, not block the admin UI.
_PROBE_TIMEOUT_S = 3.0


def _resolve_ws(workspace: str | None) -> tuple[str, Path, str]:
    """Single registry lookup: workspace id, path, display name."""
    entry, _ = resolve_workspace(workspace)
    return entry.id, Path(entry.path), entry.name


def _probe_installed_models(provider_id: str, base_url: str) -> list[str]:
    """List installed model names from a local provider's model-list endpoint.

    Native Ollama exposes ``GET /api/tags``; OpenAI-compatible servers (LM Studio, Jan) expose
    ``GET /v1/models``. Raises on transport/HTTP/JSON errors — the caller maps those to "offline".
    """
    base = base_url.rstrip("/")
    if provider_id == "ollama":
        resp = httpx.get(f"{base}/api/tags", timeout=_PROBE_TIMEOUT_S)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        return [m.get("name", "") for m in models if m.get("name")]
    resp = httpx.get(f"{base}/v1/models", timeout=_PROBE_TIMEOUT_S)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [m.get("id", "") for m in data if m.get("id")]


def _reconcile_catalog_models(provider_id: str, installed: list[str]) -> list["CatalogModelPullStatus"]:
    """Mark each cataloged model for this provider as pulled or not, with a pull hint when missing.

    The catalog id is ``provider:api_name`` (api_name is the Ollama tag, which may itself contain
    a colon). Ollama reports a default-tagged pull as ``name:latest``, so treat that as a match.
    """
    cat = get_model_catalog()
    installed_set = set(installed)
    out: list[CatalogModelPullStatus] = []
    for spec in cat.list_models(provider_id=provider_id):
        name = spec.id.split(":", 1)[1]
        pulled = name in installed_set or f"{name}:latest" in installed_set
        out.append(
            CatalogModelPullStatus(
                id=spec.id,
                name=name,
                pulled=pulled,
                pull_cmd=(None if pulled or provider_id != "ollama" else f"ollama pull {name}"),
            )
        )
    return out


@dataclass
class ProviderAddApiKeyResult:
    provider_id: str
    workspace: str
    stored: bool


@dataclass
class ProviderSetEndpointResult:
    provider_id: str
    workspace: str
    base_url: str


@dataclass
class CatalogModelPullStatus:
    """One cataloged model for a local provider and whether it is pulled on the server."""

    id: str
    name: str
    pulled: bool
    pull_cmd: str | None = None


@dataclass
class ProviderCheckResult:
    """Reachability + installed-model reconciliation for a local provider endpoint."""

    provider_id: str
    workspace: str
    base_url: str
    online: bool
    latency_ms: int | None = None
    installed: list[str] = field(default_factory=list)
    catalog_status: list[CatalogModelPullStatus] = field(default_factory=list)
    error: str | None = None


@dataclass
class ProviderRemoveResult:
    provider_id: str
    workspace: str
    removed: bool


@dataclass
class ProviderListConfiguredResult:
    workspace: str
    providers: list[dict[str, Any]]


@dataclass
class AvailableModelsListResult:
    workspace: str
    models: list[dict[str, Any]]


class ProviderAddApiKeyTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "provider_add_api_key"
    description = (
        "Store an API key for a cloud catalog provider in the workspace credential store "
        "(OS keyring + providers.json metadata). Validates provider_id against the bundled catalog."
    )
    params = {
        "provider_id": ToolParam(str, "Catalog provider id, e.g. openai, google, anthropic"),
        "api_key": ToolParam(str, "The API key string"),
        "account_id": ToolParam(
            str,
            "Vendor account id (non-secret) — required for providers like cloudflare "
            "whose REST URL embeds it",
            required=False,
        ),
        "workspace": ToolParam(str, "Workspace name or id", required=False),
    }

    def execute(
        self,
        provider_id: str,
        api_key: str,
        account_id: str | None = None,
        workspace: str | None = None,
    ) -> ProviderAddApiKeyResult:
        wid, path, ws_name = _resolve_ws(workspace)
        pid = provider_id.strip()
        key = api_key.strip()
        if not pid or not key:
            raise ValueError("provider_id and api_key are required")
        store = CredentialStore(path, wid)
        store.set_api_key(pid, key, account_id=account_id)
        return ProviderAddApiKeyResult(provider_id=pid, workspace=ws_name, stored=True)


class ProviderSetEndpointTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "provider_set_endpoint"
    description = (
        "Configure a local catalog provider (e.g. ollama, lm_studio) by its HTTP base URL — "
        "no API key. Validates the provider exists in the catalog and is locally hosted."
    )
    params = {
        "provider_id": ToolParam(str, "Catalog provider id of a local provider, e.g. ollama"),
        "base_url": ToolParam(str, "Base URL of the local server, e.g. http://localhost:11434"),
        "workspace": ToolParam(str, "Workspace name or id", required=False),
    }

    def execute(
        self,
        provider_id: str,
        base_url: str,
        workspace: str | None = None,
    ) -> ProviderSetEndpointResult:
        wid, path, ws_name = _resolve_ws(workspace)
        pid = provider_id.strip()
        url = base_url.strip()
        if not pid or not url:
            raise ValueError("provider_id and base_url are required")
        prov = get_model_catalog().get_provider(pid)
        if prov is None:
            raise ValueError(f"Unknown catalog provider_id: {pid}")
        # Local endpoints only — a cloud provider must be configured with an API key, not a URL.
        if prov.hosting != "local":
            raise ValueError(
                f"Provider {pid!r} is hosted in the cloud; set an API key instead of an endpoint."
            )
        store = CredentialStore(path, wid)
        store.set_local_endpoint(pid, url)
        # set_local_endpoint normalizes the URL (strips trailing slash); report the stored value.
        stored = store.get(pid)
        return ProviderSetEndpointResult(
            provider_id=pid,
            workspace=ws_name,
            base_url=(stored.base_url if stored and stored.base_url else url),
        )


class ProviderCheckEndpointTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "provider_check_endpoint"
    description = (
        "Probe a local provider's HTTP endpoint for reachability and list its installed models, "
        "then reconcile against the cataloged models for that provider (flags which are not pulled "
        "and the `ollama pull` command to fetch them). Offline is a normal result, not an error."
    )
    params = {
        "provider_id": ToolParam(str, "Catalog provider id of a local provider, e.g. ollama"),
        "base_url": ToolParam(
            str,
            "Endpoint to test; defaults to the stored endpoint, else the catalog default. "
            "Pass a candidate URL to test before saving.",
            required=False,
        ),
        "workspace": ToolParam(str, "Workspace name or id", required=False),
    }

    def execute(
        self,
        provider_id: str,
        base_url: str | None = None,
        workspace: str | None = None,
    ) -> ProviderCheckResult:
        wid, path, ws_name = _resolve_ws(workspace)
        pid = provider_id.strip()
        if not pid:
            raise ValueError("provider_id is required")
        prov = get_model_catalog().get_provider(pid)
        if prov is None:
            raise ValueError(f"Unknown catalog provider_id: {pid}")
        if prov.hosting != "local":
            raise ValueError(f"Provider {pid!r} is not a local provider; nothing to probe.")

        # Effective endpoint: explicit candidate > stored endpoint > catalog default.
        url = (base_url or "").strip()
        if not url:
            cred = CredentialStore(path, wid).get(pid)
            url = (cred.base_url if cred and cred.base_url else None) or (prov.default_base_url or "")
        if not url:
            raise ValueError(
                f"No base URL for {pid!r}; pass base_url or set an endpoint first."
            )

        started = time.monotonic()
        try:
            installed = _probe_installed_models(pid, url)
        except (httpx.HTTPError, ValueError, OSError) as exc:
            # Unreachable / bad response / invalid JSON → report offline (don't raise).
            log.warning(
                f"⚠️ Endpoint probe failed — HiroServer · {pid} · offline",
                error=str(exc),
                base_url=url,
            )
            return ProviderCheckResult(
                provider_id=pid,
                workspace=ws_name,
                base_url=url,
                online=False,
                error=str(exc),
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        log.info(
            f"✅ Endpoint online — HiroServer · {pid} · {len(installed)} models",
            elapsed_ms=latency_ms,
            base_url=url,
        )
        return ProviderCheckResult(
            provider_id=pid,
            workspace=ws_name,
            base_url=url,
            online=True,
            latency_ms=latency_ms,
            installed=installed,
            catalog_status=_reconcile_catalog_models(pid, installed),
        )


class ProviderRemoveTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "provider_remove"
    description = "Remove a provider's credentials from the workspace (keyring secret + metadata)."
    params = {
        "provider_id": ToolParam(str, "Catalog provider id"),
        "workspace": ToolParam(str, "Workspace name or id", required=False),
    }

    def execute(self, provider_id: str, workspace: str | None = None) -> ProviderRemoveResult:
        wid, path, ws_name = _resolve_ws(workspace)
        pid = provider_id.strip()
        if not pid:
            raise ValueError("provider_id is required")
        store = CredentialStore(path, wid)
        removed = store.remove(pid)
        return ProviderRemoveResult(provider_id=pid, workspace=ws_name, removed=removed)


class ProviderListConfiguredTool(Tool):
    name = "provider_list_configured"
    description = (
        "List providers that have credentials configured in this workspace with status summary."
    )
    params = {
        "workspace": ToolParam(str, "Workspace name or id", required=False),
    }

    def execute(self, workspace: str | None = None) -> ProviderListConfiguredResult:
        wid, path, ws_name = _resolve_ws(workspace)
        store = CredentialStore(path, wid)
        ams = AvailableModelsService(get_model_catalog(), store)
        rows = [asdict(s) for s in ams.list_configured_providers()]
        return ProviderListConfiguredResult(workspace=ws_name, providers=rows)


class AvailableModelsListTool(Tool):
    name = "available_models_list"
    description = (
        "List catalog models the workspace can use (provider must be configured). "
        "Optional filters: model_kind, model_class."
    )
    params = {
        "workspace": ToolParam(str, "Workspace name or id", required=False),
        "model_kind": ToolParam(
            str, "chat, tts, stt, embedding, image_gen", required=False
        ),
        "model_class": ToolParam(str, "e.g. agentic, fast", required=False),
    }

    def execute(
        self,
        workspace: str | None = None,
        model_kind: str | None = None,
        model_class: str | None = None,
    ) -> AvailableModelsListResult:
        wid, path, ws_name = _resolve_ws(workspace)
        store = CredentialStore(path, wid)
        ams = AvailableModelsService(get_model_catalog(), store)
        mk_raw = str(model_kind).strip() if model_kind else None
        if mk_raw == "":
            mk_raw = None
        mk: ModelKind | None = None
        if mk_raw is not None:
            allowed: tuple[ModelKind, ...] = MODEL_KINDS
            if mk_raw.lower() not in allowed:
                raise ValueError(f"model_kind must be one of {', '.join(allowed)} when provided")
            mk = mk_raw.lower()  # type: ignore[assignment]
        mc = str(model_class).strip() if model_class else None
        if mc == "":
            mc = None
        models = ams.list_available_models(model_kind=mk, model_class=mc)
        rows = [m.model_dump(mode="json") for m in models]
        return AvailableModelsListResult(workspace=ws_name, models=rows)
