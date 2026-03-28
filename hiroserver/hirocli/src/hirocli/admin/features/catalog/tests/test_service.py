"""CatalogBrowserService — tool facade tests (guidelines §7.1)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hirocli.admin.features.catalog.service import CatalogBrowserService


def test_list_providers_success() -> None:
    mock_res = MagicMock()
    mock_res.providers = [{"id": "openai", "display_name": "OpenAI"}]
    with patch(
        "hirocli.admin.features.catalog.service.LlmCatalogListProvidersTool"
    ) as T:
        T.return_value.execute.return_value = mock_res
        r = CatalogBrowserService().list_providers(None)
    assert r.ok and r.data == [{"id": "openai", "display_name": "OpenAI"}]


def test_list_providers_failure() -> None:
    with patch(
        "hirocli.admin.features.catalog.service.LlmCatalogListProvidersTool"
    ) as T:
        T.return_value.execute.side_effect = ValueError("bad hosting")
        r = CatalogBrowserService().list_providers("cloud")
    assert not r.ok


def test_list_models_success() -> None:
    mock_res = MagicMock()
    mock_res.catalog_version = 2
    mock_res.models = [{"id": "openai:gpt-5.4", "provider_id": "openai"}]
    with patch(
        "hirocli.admin.features.catalog.service.LlmCatalogListModelsTool"
    ) as T:
        T.return_value.execute.return_value = mock_res
        r = CatalogBrowserService().list_models(provider_id="openai")
    assert r.ok and r.data == (2, [{"id": "openai:gpt-5.4", "provider_id": "openai"}])
