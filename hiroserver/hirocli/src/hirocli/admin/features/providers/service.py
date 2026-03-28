"""Providers page — wraps provider tools + credential store scan; no NiceGUI (guidelines §1.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import get_model_catalog
from hirocli.domain.workspace import resolve_workspace
from hirocli.tools.provider import (
    ProviderAddApiKeyTool,
    ProviderListConfiguredTool,
    ProviderRemoveTool,
)

from hirocli.admin.shared.result import Result


class ProvidersPageService:
    """Configured providers and credential mutations for the selected workspace."""

    def list_configured(self, workspace_id: str | None) -> Result[list[dict[str, Any]]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            raw = ProviderListConfiguredTool().execute(workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(list(raw.providers))

    def list_addable_cloud_providers(self, workspace_id: str | None) -> Result[list[dict[str, str]]]:
        """Cloud catalog providers not yet configured (for Add API key dropdown)."""
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            entry, _ = resolve_workspace(workspace_id)
            store = CredentialStore(Path(entry.path), entry.id)
            configured = {p.provider_id for p in store.list_configured()}
            cat = get_model_catalog()
            addable: list[dict[str, str]] = []
            for p in cat.list_providers(hosting="cloud"):
                if p.id not in configured:
                    addable.append({"id": p.id, "display_name": p.display_name})
            return Result.success(sorted(addable, key=lambda x: x["id"]))
        except Exception as exc:
            return Result.failure(str(exc))

    def add_api_key(
        self,
        workspace_id: str | None,
        provider_id: str,
        api_key: str,
    ) -> Result[None]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        pid = provider_id.strip()
        key = api_key.strip()
        if not pid or not key:
            return Result.failure("Provider and API key are required.")
        try:
            ProviderAddApiKeyTool().execute(
                provider_id=pid,
                api_key=key,
                workspace=workspace_id,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(None)

    def remove_provider(self, workspace_id: str | None, provider_id: str) -> Result[bool]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        pid = provider_id.strip()
        if not pid:
            return Result.failure("provider_id is required.")
        try:
            raw = ProviderRemoveTool().execute(provider_id=pid, workspace=workspace_id)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(bool(raw.removed))

    def scan_environment_for_keys(self, workspace_id: str | None) -> Result[int]:
        """Import API keys from process env for providers with catalog env vars (like CLI scan-env)."""
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            entry, _ = resolve_workspace(workspace_id)
            store = CredentialStore(Path(entry.path), entry.id)
            n = store.import_detected_env_keys()
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(int(n))
