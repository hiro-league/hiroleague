"""Thin, logged wrappers over the OS keyring for storing plugin secrets.

Keyring access + error handling in one place, shared by secret stores (e.g.
``ChannelSecretStore``). Reads never raise (return None on backend failure);
writes propagate so callers can surface an actionable error. Values are stored
under a ``service`` + ``username`` pair the caller composes.

(``CredentialStore`` for provider API keys predates this module and keeps its own
keyring calls to preserve its provider-scoped logging + test injection.)
"""

from __future__ import annotations

import logging

import keyring
from keyring.errors import PasswordDeleteError

logger = logging.getLogger(__name__)


def set_secret(service: str, username: str, value: str) -> None:
    """Store a secret. Raises on backend failure (caller surfaces it)."""
    keyring.set_password(service, username, value)


def get_secret(service: str, username: str) -> str | None:
    """Read a secret, or None if absent / the backend is unavailable."""
    try:
        return keyring.get_password(service, username)
    except Exception as exc:
        logger.warning(
            "⚠️ Keyring read failed — HiroServer · %s/%s: %s", service, username, exc
        )
        return None


def delete_secret(service: str, username: str) -> None:
    """Delete a secret; a no-op if it was never stored."""
    try:
        keyring.delete_password(service, username)
    except PasswordDeleteError:
        pass
    except Exception as exc:
        logger.warning(
            "⚠️ Keyring delete failed — HiroServer · %s/%s: %s", service, username, exc
        )
