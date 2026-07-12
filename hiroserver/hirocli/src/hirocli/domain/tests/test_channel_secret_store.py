"""Channel secret store + push-time resolution (design §5.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain import channel_secret_store as css
from hirocli.domain.channel_secret_store import (
    SECRET_MARKER,
    ChannelSecretStore,
    is_secret_marker,
    resolve_channel_secrets,
)


@pytest.fixture
def fake_keyring(monkeypatch):
    """Back the keyring wrappers with an in-memory dict keyed by (service, username)."""
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(css.keyring_secrets, "set_secret", lambda s, u, v: store.__setitem__((s, u), v))
    monkeypatch.setattr(css.keyring_secrets, "get_secret", lambda s, u: store.get((s, u)))
    monkeypatch.setattr(css.keyring_secrets, "delete_secret", lambda s, u: store.pop((s, u), None))
    return store


def test_marker_helpers() -> None:
    assert is_secret_marker(dict(SECRET_MARKER))
    assert not is_secret_marker("plain")
    assert not is_secret_marker({"other": True})


def test_set_get_delete(fake_keyring) -> None:
    s = ChannelSecretStore(Path("/ws"), "ws1")
    assert s.get("telegram", "bot_token") is None
    s.set("telegram", "bot_token", "SECRET123")
    assert s.get("telegram", "bot_token") == "SECRET123"
    assert s.has("telegram", "bot_token")
    # Namespaced by (workspace, channel): a different channel doesn't see it.
    assert s.get("whatsapp", "bot_token") is None
    s.delete("telegram", "bot_token")
    assert s.get("telegram", "bot_token") is None


def test_set_wraps_backend_failure(monkeypatch) -> None:
    def boom(*_a):
        raise OSError("no keyring")

    monkeypatch.setattr(css.keyring_secrets, "set_secret", boom)
    s = ChannelSecretStore(Path("/ws"), "ws1")
    with pytest.raises(RuntimeError, match="Keyring is unavailable"):
        s.set("telegram", "bot_token", "x")


def test_resolve_swaps_markers_for_values(fake_keyring) -> None:
    s = ChannelSecretStore(Path("/ws"), "ws1")
    s.set("telegram", "bot_token", "TObot")
    config = {"bot_token": dict(SECRET_MARKER), "polling": True}
    resolved = resolve_channel_secrets(Path("/ws"), "telegram", config, store=s)
    assert resolved == {"bot_token": "TObot", "polling": True}


def test_resolve_drops_unset_secret(fake_keyring) -> None:
    s = ChannelSecretStore(Path("/ws"), "ws1")
    config = {"bot_token": dict(SECRET_MARKER), "polling": True}
    resolved = resolve_channel_secrets(Path("/ws"), "telegram", config, store=s)
    # Marker present but nothing in the keyring → the key is dropped, not bogus.
    assert resolved == {"polling": True}


def test_resolve_no_markers_is_passthrough_copy() -> None:
    config = {"a": 1, "b": "two"}
    resolved = resolve_channel_secrets(Path("/ws"), "telegram", config)
    assert resolved == config and resolved is not config
