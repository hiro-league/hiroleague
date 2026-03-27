"""Provider credentials and workspace-available LLM tools (Phase 2a)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..domain.available_models import AvailableModelsService
from ..domain.credential_store import CredentialStore
from ..domain.model_catalog import ModelKind, get_model_catalog
from ..domain.workspace import WorkspaceError, resolve_workspace
from .base import Tool, ToolParam


def _resolve_ws(workspace: str | None) -> tuple[str, Path, str]:
    """Single registry lookup: workspace id, path, display name."""
    entry, _ = resolve_workspace(workspace)
    return entry.id, Path(entry.path), entry.name


@dataclass
class ProviderAddApiKeyResult:
    provider_id: str
    workspace: str
    stored: bool


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
    name = "provider_add_api_key"
    description = (
        "Store an API key for a cloud catalog provider in the workspace credential store "
        "(OS keyring + providers.json metadata). Validates provider_id against the bundled catalog."
    )
    params = {
        "provider_id": ToolParam(str, "Catalog provider id, e.g. openai, google, anthropic"),
        "api_key": ToolParam(str, "The API key string"),
        "workspace": ToolParam(str, "Workspace name or id", required=False),
    }

    def execute(
        self,
        provider_id: str,
        api_key: str,
        workspace: str | None = None,
    ) -> ProviderAddApiKeyResult:
        wid, path, ws_name = _resolve_ws(workspace)
        pid = provider_id.strip()
        key = api_key.strip()
        if not pid or not key:
            raise ValueError("provider_id and api_key are required")
        store = CredentialStore(path, wid)
        store.set_api_key(pid, key)
        return ProviderAddApiKeyResult(provider_id=pid, workspace=ws_name, stored=True)


class ProviderRemoveTool(Tool):
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
            allowed: tuple[ModelKind, ...] = (
                "chat",
                "tts",
                "stt",
                "embedding",
                "image_gen",
            )
            if mk_raw.lower() not in allowed:
                raise ValueError(f"model_kind must be one of {', '.join(allowed)} when provided")
            mk = mk_raw.lower()  # type: ignore[assignment]
        mc = str(model_class).strip() if model_class else None
        if mc == "":
            mc = None
        models = ams.list_available_models(model_kind=mk, model_class=mc)
        rows = [m.model_dump(mode="json") for m in models]
        return AvailableModelsListResult(workspace=ws_name, models=rows)
