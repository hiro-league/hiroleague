"""Per-workspace provider credentials: OS keyring for secrets, providers.json for metadata."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import keyring
from hiro_commons.constants.storage import PROVIDERS_FILENAME
from keyring.errors import PasswordDeleteError
from pydantic import BaseModel, Field

from .model_catalog import get_model_catalog

logger = logging.getLogger(__name__)

AuthMethod = Literal["api_key", "local_endpoint", "oauth"]

KEYRING_USERNAME = "api_key"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _service_name(workspace_id: str, provider_id: str) -> str:
    return f"hiroleague:{workspace_id}:{provider_id}"


class ProviderMetadata(BaseModel):
    """Non-secret metadata for one configured provider (stored in providers.json)."""

    provider_id: str
    auth_method: AuthMethod
    created_at: str
    updated_at: str
    base_url: str | None = None
    verified_at: str | None = None
    token_expires_at: str | None = None
    oauth_scopes: list[str] | None = None


class ProvidersDocument(BaseModel):
    version: int = 1
    providers: list[ProviderMetadata] = Field(default_factory=list)


@dataclass
class ProviderCredential:
    """Unified view of a configured provider (metadata + secret when applicable)."""

    provider_id: str
    auth_method: AuthMethod
    api_key: str | None = None
    base_url: str | None = None


class CredentialStore:
    """Secrets in OS keyring; non-secret state in ``<workspace>/providers.json``."""

    def __init__(
        self,
        workspace_path: Path,
        workspace_id: str,
        *,
        _test_secrets: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self._workspace_path = workspace_path
        self._workspace_id = workspace_id
        self._test_secrets = _test_secrets
        self._doc = self._load_doc()
        if _test_secrets is None:
            kr = keyring.get_keyring()
            # DEBUG: CredentialStore is constructed frequently (resolve_llm, tools, STT);
            # INFO here would flood operational logs.
            logger.debug(
                "Credential store ready — HiroServer · keyring backend · %s",
                kr.__class__.__name__,
            )

    def providers_file(self) -> Path:
        return self._workspace_path / PROVIDERS_FILENAME

    def _load_doc(self) -> ProvidersDocument:
        path = self.providers_file()
        if not path.exists():
            return ProvidersDocument()
        try:
            return ProvidersDocument.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception(
                "❌ Failed to load providers.json — workspace · resetting empty document",
            )
            return ProvidersDocument()

    def _save_doc(self) -> None:
        self._workspace_path.mkdir(parents=True, exist_ok=True)
        self.providers_file().write_text(
            self._doc.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _meta_for(self, provider_id: str) -> ProviderMetadata | None:
        for p in self._doc.providers:
            if p.provider_id == provider_id:
                return p
        return None

    def _set_password(self, provider_id: str, secret: str) -> None:
        svc = _service_name(self._workspace_id, provider_id)
        if self._test_secrets is not None:
            self._test_secrets[(svc, KEYRING_USERNAME)] = secret
            return
        keyring.set_password(svc, KEYRING_USERNAME, secret)

    def _get_password(self, provider_id: str) -> str | None:
        svc = _service_name(self._workspace_id, provider_id)
        if self._test_secrets is not None:
            return self._test_secrets.get((svc, KEYRING_USERNAME))
        try:
            return keyring.get_password(svc, KEYRING_USERNAME)
        except Exception as exc:
            logger.warning(
                "⚠️ Keyring read failed — HiroServer · provider · falling back to env if any",
                provider_id=provider_id,
                error=str(exc),
            )
            return None

    def _delete_password(self, provider_id: str) -> None:
        svc = _service_name(self._workspace_id, provider_id)
        if self._test_secrets is not None:
            self._test_secrets.pop((svc, KEYRING_USERNAME), None)
            return
        try:
            keyring.delete_password(svc, KEYRING_USERNAME)
        except PasswordDeleteError:
            pass
        except Exception as exc:
            logger.warning(
                "⚠️ Keyring delete failed — HiroServer · provider",
                provider_id=provider_id,
                error=str(exc),
            )

    def _api_key_from_env(self, provider_id: str) -> str | None:
        cat = get_model_catalog()
        prov = cat.get_provider(provider_id)
        if prov is None:
            return None
        for env_name in prov.credential_env_keys:
            val = os.environ.get(env_name)
            if val:
                return val
        return None

    def set_api_key(self, provider_id: str, api_key: str) -> None:
        cat = get_model_catalog()
        if cat.get_provider(provider_id) is None:
            raise ValueError(f"Unknown catalog provider_id: {provider_id}")
        now = _utc_now_iso()
        try:
            self._set_password(provider_id, api_key)
        except Exception as exc:
            logger.error(
                "❌ Could not store API key in keyring — HiroServer · provider\n"
                "Install a platform keyring backend or set API keys via environment variables.",
                provider_id=provider_id,
                error=str(exc),
                exc_info=True,
            )
            raise RuntimeError(
                "Keyring is not available or refused to store the secret. "
                "Set the provider's API key in your environment instead, or fix the OS keyring."
            ) from exc

        existing = self._meta_for(provider_id)
        if existing is None:
            self._doc.providers.append(
                ProviderMetadata(
                    provider_id=provider_id,
                    auth_method="api_key",
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            existing.auth_method = "api_key"
            existing.updated_at = now
            existing.base_url = None
        self._save_doc()

    def set_local_endpoint(self, provider_id: str, base_url: str) -> None:
        cat = get_model_catalog()
        prov = cat.get_provider(provider_id)
        if prov is None:
            raise ValueError(f"Unknown catalog provider_id: {provider_id}")
        now = _utc_now_iso()
        url = base_url.rstrip("/")
        existing = self._meta_for(provider_id)
        if existing is None:
            self._doc.providers.append(
                ProviderMetadata(
                    provider_id=provider_id,
                    auth_method="local_endpoint",
                    created_at=now,
                    updated_at=now,
                    base_url=url,
                )
            )
        else:
            existing.auth_method = "local_endpoint"
            existing.updated_at = now
            existing.base_url = url
        self._save_doc()

    def get(self, provider_id: str) -> ProviderCredential | None:
        meta = self._meta_for(provider_id)
        if meta is None:
            return None
        if meta.auth_method == "api_key":
            key = self.get_api_key(provider_id)
            return ProviderCredential(
                provider_id=provider_id,
                auth_method="api_key",
                api_key=key,
            )
        if meta.auth_method == "local_endpoint":
            return ProviderCredential(
                provider_id=provider_id,
                auth_method="local_endpoint",
                base_url=meta.base_url,
            )
        return ProviderCredential(
            provider_id=provider_id,
            auth_method=meta.auth_method,
            base_url=meta.base_url,
        )

    def list_configured(self) -> list[ProviderMetadata]:
        return sorted(self._doc.providers, key=lambda p: p.provider_id)

    def is_configured(self, provider_id: str) -> bool:
        return self._meta_for(provider_id) is not None

    def remove(self, provider_id: str) -> bool:
        meta = self._meta_for(provider_id)
        if meta is None:
            return False
        if meta.auth_method == "api_key":
            self._delete_password(provider_id)
        self._doc.providers = [p for p in self._doc.providers if p.provider_id != provider_id]
        self._save_doc()
        return True

    def import_detected_env_keys(self) -> int:
        """Configure providers for which a catalog env var is set (setup / scan-env).

        Skips providers that are already configured. Returns count of newly stored keys.
        """
        cat = get_model_catalog()
        imported = 0
        for p in cat.list_providers():
            if not p.credential_env_keys or self.is_configured(p.id):
                continue
            for env_name in p.credential_env_keys:
                val = os.environ.get(env_name)
                if not val:
                    continue
                try:
                    self.set_api_key(p.id, val)
                    imported += 1
                except RuntimeError:
                    logger.warning(
                        "⚠️ Env key found but keyring store failed — HiroServer · provider · %s",
                        p.id,
                        env_key=env_name,
                    )
                break
        return imported

    def get_api_key(self, provider_id: str) -> str | None:
        meta = self._meta_for(provider_id)
        if meta is None or meta.auth_method != "api_key":
            return None
        key = self._get_password(provider_id)
        if key:
            return key
        return self._api_key_from_env(provider_id)
