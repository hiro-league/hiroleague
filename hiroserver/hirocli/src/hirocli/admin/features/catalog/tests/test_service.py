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
    mock_res.catalog_version = "0.2.0"
    mock_res.models = [{"id": "openai:gpt-5.4", "provider_id": "openai"}]
    with patch(
        "hirocli.admin.features.catalog.service.LlmCatalogListModelsTool"
    ) as T:
        T.return_value.execute.return_value = mock_res
        r = CatalogBrowserService().list_models(provider_id="openai")
    assert r.ok and r.data == ("0.2.0", [{"id": "openai:gpt-5.4", "provider_id": "openai"}])


def test_reload_from_disk_success() -> None:
    mock_cat = MagicMock()
    mock_cat.catalog_version = "9.9.9"
    mock_cat.list_providers.return_value = [1, 2]
    mock_cat.list_models.return_value = [1, 2, 3]
    with patch(
        "hirocli.admin.features.catalog.service.reload_model_catalog",
        return_value=mock_cat,
    ):
        r = CatalogBrowserService().reload_from_disk()
    assert r.ok
    assert r.data == {"catalog_version": "9.9.9", "provider_count": 2, "model_count": 3}


def test_reload_from_disk_failure() -> None:
    with patch(
        "hirocli.admin.features.catalog.service.reload_model_catalog",
        side_effect=RuntimeError("bad yaml"),
    ):
        r = CatalogBrowserService().reload_from_disk()
    assert not r.ok
