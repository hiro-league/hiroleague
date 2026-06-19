"""ProvidersPageService tests (guidelines §7.1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from hirocli.admin.features.providers.service import ProvidersPageService
from hirocli.tools.provider import ProviderCheckEndpointTool, ProviderSetEndpointTool


def _ws_entry() -> MagicMock:
    entry = MagicMock()
    entry.id = "wid"
    entry.path = "/tmp/ws"
    entry.name = "tf"
    return entry


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


def test_set_local_endpoint_blank_fails() -> None:
    r = ProvidersPageService().set_local_endpoint("ws1", "ollama", "   ")
    assert not r.ok and "required" in (r.error or "").lower()


def test_set_local_endpoint_delegates_to_tool() -> None:
    with patch(
        "hirocli.admin.features.providers.service.ProviderSetEndpointTool"
    ) as T:
        r = ProvidersPageService().set_local_endpoint(
            "ws1", "ollama", "http://localhost:11434"
        )
    assert r.ok
    T.return_value.execute.assert_called_once_with(
        provider_id="ollama",
        base_url="http://localhost:11434",
        workspace="ws1",
    )


def test_list_addable_includes_local_and_cloud() -> None:
    """Addable list spans cloud (api_key) and local (local_endpoint) providers; uses real catalog."""
    entry = MagicMock()
    entry.id = "wid"
    entry.path = "/tmp/ws"
    store = MagicMock()
    store.list_configured.return_value = []  # nothing configured → everything is addable
    with (
        patch(
            "hirocli.admin.features.providers.service.resolve_workspace",
            return_value=(entry, None),
        ),
        patch(
            "hirocli.admin.features.providers.service.CredentialStore",
            return_value=store,
        ),
    ):
        r = ProvidersPageService().list_addable_providers("ws1")
    assert r.ok
    by_id = {row["id"]: row for row in r.data}
    assert by_id["ollama"]["auth_method"] == "local_endpoint"
    assert by_id["ollama"]["default_base_url"] == "http://localhost:11434"
    assert by_id["openai"]["auth_method"] == "api_key"


def test_set_endpoint_tool_rejects_cloud_provider() -> None:
    """The shared tool refuses to store an endpoint for a cloud provider (real bundled catalog)."""
    entry = MagicMock()
    entry.id = "wid"
    entry.path = "/tmp/ws"
    store = MagicMock()
    with (
        patch(
            "hirocli.tools.provider.resolve_workspace",
            return_value=(entry, None),
        ),
        patch(
            "hirocli.tools.provider.CredentialStore",
            return_value=store,
        ),
    ):
        try:
            ProviderSetEndpointTool().execute(
                provider_id="openai", base_url="http://localhost:11434"
            )
        except ValueError as exc:
            assert "cloud" in str(exc).lower()
        else:
            raise AssertionError("expected ValueError for cloud provider")
    store.set_local_endpoint.assert_not_called()


def test_check_endpoint_online_reconciles_installed_models() -> None:
    """Online probe of /api/tags reconciles cataloged models (exact + :latest matching)."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "models": [{"name": "gemma4:12b"}, {"name": "llama3.3:latest"}]
    }
    with (
        patch("hirocli.tools.provider.resolve_workspace", return_value=(_ws_entry(), None)),
        patch("hirocli.tools.provider.httpx.get", return_value=resp) as G,
    ):
        result = ProviderCheckEndpointTool().execute(
            provider_id="ollama", base_url="http://localhost:11434"
        )
    assert result.online and result.error is None
    assert G.call_args[0][0] == "http://localhost:11434/api/tags"
    by_name = {s.name: s for s in result.catalog_status}
    assert by_name["gemma4:12b"].pulled  # exact tag match
    assert by_name["llama3.3"].pulled  # matched via :latest
    assert not by_name["gemma4:26b"].pulled
    assert by_name["gemma4:26b"].pull_cmd == "ollama pull gemma4:26b"


def test_check_endpoint_offline_on_connect_error() -> None:
    """An unreachable endpoint is a successful 'offline' result, not a raised error."""
    with (
        patch("hirocli.tools.provider.resolve_workspace", return_value=(_ws_entry(), None)),
        patch(
            "hirocli.tools.provider.httpx.get",
            side_effect=httpx.ConnectError("connection refused"),
        ),
    ):
        result = ProviderCheckEndpointTool().execute(
            provider_id="ollama", base_url="http://localhost:11434"
        )
    assert not result.online
    assert "refused" in (result.error or "")
    assert result.catalog_status == []


def test_check_endpoint_rejects_cloud_provider() -> None:
    with patch("hirocli.tools.provider.resolve_workspace", return_value=(_ws_entry(), None)):
        try:
            ProviderCheckEndpointTool().execute(provider_id="openai", base_url="http://x")
        except ValueError as exc:
            assert "local" in str(exc).lower()
        else:
            raise AssertionError("expected ValueError for cloud provider")


def test_service_check_endpoint_delegates_and_serializes() -> None:
    from hirocli.tools.provider import ProviderCheckResult

    fake = ProviderCheckResult(
        provider_id="ollama", workspace="tf", base_url="http://localhost:11434", online=True
    )
    with patch(
        "hirocli.admin.features.providers.service.ProviderCheckEndpointTool"
    ) as T:
        T.return_value.execute.return_value = fake
        r = ProvidersPageService().check_endpoint("ws1", "ollama", None)
    assert r.ok and r.data["online"] is True and r.data["provider_id"] == "ollama"
