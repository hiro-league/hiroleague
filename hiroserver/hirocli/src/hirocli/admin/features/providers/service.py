"""Provider operations for the admin API."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import get_model_catalog
from hirocli.domain.workspace import resolve_workspace
from hirocli.tools.provider import (
    ProviderAddApiKeyTool,
    ProviderCheckEndpointTool,
    ProviderListConfiguredTool,
    ProviderRemoveTool,
    ProviderSetEndpointTool,
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

    def list_addable_providers(self, workspace_id: str | None) -> Result[list[dict[str, Any]]]:
        """Catalog providers not yet configured (Add-provider dropdown).

        Includes both cloud (API key) and local (HTTP endpoint) providers; the ``auth_method``
        field tells the add dialog which form to render. The synthetic in-process ``local``
        provider is not a catalog row, so it never appears here.
        """
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            entry, _ = resolve_workspace(workspace_id)
            store = CredentialStore(Path(entry.path), entry.id)
            configured = {p.provider_id for p in store.list_configured()}
            cat = get_model_catalog()
            addable: list[dict[str, Any]] = []
            for p in cat.list_providers():
                if p.id in configured:
                    continue
                addable.append(
                    {
                        "id": p.id,
                        "display_name": p.display_name,
                        "hosting": p.hosting,
                        # Drives the add dialog's form: API key vs local HTTP endpoint.
                        "auth_method": "local_endpoint" if p.hosting == "local" else "api_key",
                        "default_base_url": p.default_base_url,
                        # Cloudflare-style: the add dialog shows an extra account-id input.
                        "requires_account_id": p.requires_account_id,
                    }
                )
            return Result.success(sorted(addable, key=lambda x: x["id"]))
        except Exception as exc:
            return Result.failure(str(exc))

    def add_api_key(
        self,
        workspace_id: str | None,
        provider_id: str,
        api_key: str,
        account_id: str | None = None,
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
                account_id=account_id,
                workspace=workspace_id,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(None)

    def set_local_endpoint(
        self,
        workspace_id: str | None,
        provider_id: str,
        base_url: str,
    ) -> Result[None]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        pid = provider_id.strip()
        url = base_url.strip()
        if not pid or not url:
            return Result.failure("Provider and base URL are required.")
        try:
            ProviderSetEndpointTool().execute(
                provider_id=pid,
                base_url=url,
                workspace=workspace_id,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(None)

    def check_endpoint(
        self,
        workspace_id: str | None,
        provider_id: str,
        base_url: str | None = None,
    ) -> Result[dict[str, Any]]:
        """Probe a local provider's endpoint (reachability + installed-model reconciliation).

        ``base_url`` is optional — when omitted the stored/catalog endpoint is probed; pass a
        candidate URL to test before saving. Offline is a successful Result with ``online: false``.
        """
        if not workspace_id:
            return Result.failure("No workspace selected.")
        pid = provider_id.strip()
        if not pid:
            return Result.failure("Provider is required.")
        try:
            result = ProviderCheckEndpointTool().execute(
                provider_id=pid,
                base_url=base_url,
                workspace=workspace_id,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(asdict(result))

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
