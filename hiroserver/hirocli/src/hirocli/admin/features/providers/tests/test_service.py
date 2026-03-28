"""ProvidersPageService tests (guidelines §7.1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from hirocli.admin.features.providers.service import ProvidersPageService


def test_list_configured_no_workspace() -> None:
    r = ProvidersPageService().list_configured(None)
    assert not r.ok and "workspace" in (r.error or "").lower()


def test_list_configured_success() -> None:
    mock_res = MagicMock()
    mock_res.providers = [{"provider_id": "openai", "display_name": "OpenAI"}]
    with patch(
        "hirocli.admin.features.providers.service.ProviderListConfiguredTool"
    ) as T:
        T.return_value.execute.return_value = mock_res
        r = ProvidersPageService().list_configured("ws1")
    assert r.ok and r.data == mock_res.providers


def test_add_api_key_empty() -> None:
    r = ProvidersPageService().add_api_key("ws1", "openai", "   ")
    assert not r.ok


def test_scan_env_success() -> None:
    entry = MagicMock()
    entry.id = "wid"
    entry.path = "/tmp/ws"
    store = MagicMock()
    store.import_detected_env_keys.return_value = 2
    with (
        patch(
            "hirocli.admin.features.providers.service.resolve_workspace",
            return_value=(entry, None),
        ),
        patch(
            "hirocli.admin.features.providers.service.CredentialStore",
            return_value=store,
        ) as CS,
    ):
        r = ProvidersPageService().scan_environment_for_keys("ws1")
    assert r.ok and r.data == 2
    CS.assert_called_once_with(Path("/tmp/ws"), "wid")
