from __future__ import annotations

from hirocli.environment import (
    DEV_DOCS_BASE_URL,
    PROD_DOCS_BASE_URL,
    docs_base_url,
    get_environment_config,
)


def test_environment_defaults_to_prod_docs(monkeypatch) -> None:
    monkeypatch.delenv("HIRO_ENV", raising=False)
    monkeypatch.delenv("HIRO_DOCS_BASE_URL", raising=False)

    config = get_environment_config()

    assert config.hiro_env == "prod"
    assert config.docs_base_url == PROD_DOCS_BASE_URL


def test_dev_environment_uses_local_docs(monkeypatch) -> None:
    monkeypatch.setenv("HIRO_ENV", "dev")
    monkeypatch.delenv("HIRO_DOCS_BASE_URL", raising=False)

    config = get_environment_config()

    assert config.hiro_env == "dev"
    assert config.docs_base_url == DEV_DOCS_BASE_URL


def test_docs_url_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("HIRO_ENV", "dev")
    monkeypatch.setenv("HIRO_DOCS_BASE_URL", "https://preview.docs.example/")

    assert docs_base_url() == "https://preview.docs.example"
