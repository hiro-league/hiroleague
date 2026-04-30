from __future__ import annotations

from hirogateway.environment import current_hiro_env, get_environment_config


def test_environment_defaults_to_prod(monkeypatch) -> None:
    monkeypatch.delenv("HIRO_ENV", raising=False)

    config = get_environment_config()

    assert config.hiro_env == "prod"
    assert config.is_prod is True
    assert config.is_dev is False


def test_dev_environment_aliases(monkeypatch) -> None:
    monkeypatch.setenv("HIRO_ENV", "local")

    config = get_environment_config()

    assert config.hiro_env == "dev"
    assert config.is_dev is True
    assert config.is_prod is False


def test_custom_environment_is_preserved(monkeypatch) -> None:
    monkeypatch.setenv("HIRO_ENV", "staging")

    assert current_hiro_env() == "staging"
