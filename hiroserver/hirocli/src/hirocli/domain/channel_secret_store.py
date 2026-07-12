"""Channel plugin secrets (design §5.6).

A channel config field declared ``secret: true`` in the plugin's schema (§5.1) is
NOT stored in ``channel_plugins.config``. Its value goes to the OS keyring
(``ChannelSecretStore``); the config row keeps only a ``SECRET_MARKER`` presence
sentinel. At push time ``resolve_channel_secrets`` swaps markers for real values
so the plugin receives usable config while the database never holds the secret.

Keyring layout mirrors the provider ``CredentialStore``:
``service = hiroleague:{workspace_id}:channel:{channel}``, ``username = field``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import keyring_secrets
from .workspace import workspace_id_for_path

logger = logging.getLogger(__name__)

_SERVICE_PREFIX = "hiroleague"

# Presence sentinel written into channel_plugins.config in place of a secret value.
# The real value lives only in the keyring; this just records "a secret is set".
SECRET_MARKER: dict[str, bool] = {"__secret__": True}


def is_secret_marker(value: Any) -> bool:
    """True if *value* is the stored-secret sentinel (not a real config value)."""
    return isinstance(value, dict) and value.get("__secret__") is True


class ChannelSecretStore:
    """Per-workspace store for channel plugin secrets, backed by the OS keyring."""

    def __init__(self, workspace_path: Path, workspace_id: str) -> None:
        self._workspace_path = workspace_path
        self._workspace_id = workspace_id

    def _service(self, channel: str) -> str:
        return f"{_SERVICE_PREFIX}:{self._workspace_id}:channel:{channel}"

    def set(self, channel: str, key: str, value: str) -> None:
        try:
            keyring_secrets.set_secret(self._service(channel), key, value)
        except Exception as exc:
            logger.error(
                "❌ Could not store channel secret — HiroServer · %s.%s: %s",
                channel,
                key,
                exc,
                exc_info=True,
            )
            raise RuntimeError(
                "Keyring is unavailable or refused to store the secret. Fix the OS "
                "keyring, or provide the value another way."
            ) from exc

    def get(self, channel: str, key: str) -> str | None:
        return keyring_secrets.get_secret(self._service(channel), key)

    def delete(self, channel: str, key: str) -> None:
        keyring_secrets.delete_secret(self._service(channel), key)

    def has(self, channel: str, key: str) -> bool:
        return self.get(channel, key) is not None


def resolve_channel_secrets(
    workspace_path: Path,
    channel: str,
    config: dict[str, Any],
    *,
    store: ChannelSecretStore | None = None,
) -> dict[str, Any]:
    """Return *config* with every secret marker replaced by its keyring value.

    A marker whose secret can't be read (unset, or workspace not in the registry)
    is dropped, so the plugin never receives a bogus value. Non-secret keys pass
    through unchanged. Returns a fresh dict (never mutates the input).
    """
    if not any(is_secret_marker(v) for v in config.values()):
        return dict(config)

    if store is None:
        wid = workspace_id_for_path(workspace_path)
        if wid is None:
            logger.warning(
                "⚠️ Cannot resolve channel secrets — workspace not in registry (%s)",
                channel,
            )
            return {k: v for k, v in config.items() if not is_secret_marker(v)}
        store = ChannelSecretStore(workspace_path, wid)

    resolved: dict[str, Any] = {}
    for key, value in config.items():
        if not is_secret_marker(value):
            resolved[key] = value
            continue
        secret = store.get(channel, key)
        if secret is not None:
            resolved[key] = secret
        else:
            logger.warning(
                "⚠️ Channel secret marked but absent from keyring — %s.%s", channel, key
            )
    return resolved
