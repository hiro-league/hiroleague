from __future__ import annotations

from hirocli.environment import (
    DEV_DOCS_BASE_URL,
    PROD_DOCS_BASE_URL,
    default_workspace_log_level,
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


def test_default_workspace_log_level_is_info_in_prod(monkeypatch) -> None:
    monkeypatch.delenv("HIRO_ENV", raising=False)
    assert default_workspace_log_level() == "INFO"
    monkeypatch.setenv("HIRO_ENV", "production")
    assert default_workspace_log_level() == "INFO"


def test_default_workspace_log_level_is_debug_outside_prod(monkeypatch) -> None:
    monkeypatch.setenv("HIRO_ENV", "dev")
    assert default_workspace_log_level() == "DEBUG"
    monkeypatch.setenv("HIRO_ENV", "staging")
    assert default_workspace_log_level() == "DEBUG"
