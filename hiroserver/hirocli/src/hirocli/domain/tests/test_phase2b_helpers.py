"""Phase 2b helpers: CLI provisioning selection + STT construction."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from hirocli.commands.provider import (
    discovered_env_keys_rows,
    interactive_credential_provisioning,
    parse_index_selection,
)
from hirocli.domain.preferences import WorkspacePreferences


def test_parse_index_selection_all_none_indices() -> None:
    assert parse_index_selection("all", 3) == {0, 1, 2}
    assert parse_index_selection("NONE", 3) == set()
    assert parse_index_selection("2, 3", 3) == {1, 2}


def test_parse_index_selection_invalid() -> None:
    assert parse_index_selection("0", 2) is None
    assert parse_index_selection("99", 2) is None
    assert parse_index_selection("foo", 2) is None


def test_discovered_env_keys_rows_unique_provider_ids() -> None:
    """At most one row per catalog provider (first set env var wins)."""
    rows = discovered_env_keys_rows()
    ids = [p.id for p, _e, _v in rows]
    assert len(ids) == len(set(ids))


def test_interactive_credential_provisioning_imports_selected(tmp_path: Path) -> None:
    from rich.console import Console

    mock_prov = MagicMock()
    mock_prov.id = "openai"
    mock_prov.display_name = "OpenAI"
    mock_prov.credential_env_keys = ["OPENAI_API_KEY"]
    rows = [(mock_prov, "OPENAI_API_KEY", "sk-secret")]

    store = MagicMock()
    store.is_configured.return_value = False
    store.list_configured.return_value = []
    mock_cat = MagicMock()
    mock_cat.list_providers.return_value = []

    console = Console(file=StringIO(), force_terminal=True, width=120)
    with (
        patch("hirocli.commands.provider.discovered_env_keys_rows", return_value=rows),
        patch("hirocli.commands.provider.CredentialStore", return_value=store),
        patch("hirocli.commands.provider.get_model_catalog", return_value=mock_cat),
        patch("hirocli.commands.provider.print_provider_summary_table"),
        patch("hirocli.commands.provider.Confirm.ask", side_effect=[True, False]),
        patch("hirocli.commands.provider.Prompt.ask", return_value="all"),
    ):
        interactive_credential_provisioning(tmp_path, "w1", "ws", console)

    store.set_api_key.assert_called_once_with("openai", "sk-secret")


def test_create_stt_service_injects_credential_store_key(tmp_path: Path) -> None:
    from hirocli.domain.preferences import LLMPreferences
    from hirocli.services.stt import create_stt_service

    mock_spec = MagicMock()
    mock_spec.provider_id = "openai"
    prefs = WorkspacePreferences(
        llm=LLMPreferences(default_stt="openai:gpt-4o-transcribe"),
    )
    mock_store = MagicMock()
    mock_store.get_api_key.return_value = "sk-stt"
    with (
        patch("hirocli.domain.preferences.load_preferences", return_value=prefs),
        patch("hirocli.domain.workspace.workspace_id_for_path", return_value="w1"),
        patch("hirocli.domain.preferences.resolve_stt_model", return_value="openai:gpt-4o-transcribe"),
        patch("hirocli.domain.model_catalog.get_model_catalog") as gmc,
        patch("hirocli.domain.credential_store.CredentialStore", return_value=mock_store),
    ):
        gmc.return_value.get_model.return_value = mock_spec
        svc = create_stt_service(tmp_path)
    mock_store.get_api_key.assert_called_once_with("openai")
    assert svc.providers
    assert getattr(svc.providers[0], "_api_key", None) == "sk-stt"
