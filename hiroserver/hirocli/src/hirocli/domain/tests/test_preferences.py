"""Tests for preferences resolution (canonical ids + availability)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_catalog import ModelCatalog, clear_model_catalog_cache
from hirocli.domain.preferences import (
    LLMPreferences,
    MemoryPreferences,
    ModelTuning,
    WorkspacePreferences,
    resolve_llm,
    resolve_summarization_llm,
)


@pytest.fixture(autouse=True)
def _clear_cat() -> None:
    clear_model_catalog_cache()
    yield
    clear_model_catalog_cache()


def _fixture_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Minimal registry pointing tmp_path as workspace."""
    from hirocli.domain import workspace as ws_mod

    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    reg = ws_mod.WorkspaceRegistry(
        default_workspace=wid,
        workspaces={
            wid: ws_mod.WorkspaceEntry(
                id=wid,
                name="t",
                path=str(tmp_path.resolve()),
                port_slot=0,
            ),
        },
    )
    monkeypatch.setattr(ws_mod, "load_registry", lambda: reg)
    return wid


def _patch_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hirocli.domain import model_catalog as mc

    doc = {
        "catalog_version": 1,
        "providers": [
            {
                "id": "openai",
                "display_name": "OpenAI",
                "hosting": "cloud",
                "credential_env_keys": ["OPENAI_API_KEY"],
                "metadata_updated_at": "2026-01-01",
            },
        ],
        "models": [
            {
                "id": "openai:gpt-test",
                "provider_id": "openai",
                "display_name": "G",
                "model_kind": "chat",
            },
            {
                "id": "openai:gpt-other",
                "provider_id": "openai",
                "display_name": "G2",
                "model_kind": "chat",
            },
        ],
    }
    p = tmp_path / "cat.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cat = ModelCatalog.load_from_path(p)
    monkeypatch.setattr(mc, "get_model_catalog", lambda: cat)
    monkeypatch.setattr("hirocli.domain.credential_store.get_model_catalog", lambda: cat)


def test_resolve_llm_none_without_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    prefs = WorkspacePreferences()
    assert resolve_llm(prefs, tmp_path, "chat") is None


def test_resolve_llm_with_default_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    secrets: dict[tuple[str, str], str] = {}
    CredentialStore(tmp_path, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", _test_secrets=secrets).set_api_key(
        "openai", "sk"
    )
    prefs = WorkspacePreferences(
        llm=LLMPreferences(
            default_chat="openai:gpt-test",
            tuning={"openai:gpt-test": ModelTuning(temperature=0.5, max_tokens=512)},
        ),
    )
    r = resolve_llm(prefs, tmp_path, "chat")
    assert r is not None
    assert r.model_id == "openai:gpt-test"
    assert r.temperature == 0.5
    assert r.max_tokens == 512


def test_resolve_summarization_fallback_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    CredentialStore(tmp_path, wid, _test_secrets={}).set_api_key("openai", "sk")
    prefs = WorkspacePreferences(
        llm=LLMPreferences(default_chat="openai:gpt-test"),
        memory=MemoryPreferences(summarization_llm_id=None),
    )
    r = resolve_summarization_llm(prefs, tmp_path)
    assert r is not None and r.model_id == "openai:gpt-test"


def test_resolve_summarization_memory_id_overrides_default_summarization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_workspace(tmp_path, monkeypatch)
    _patch_catalog(tmp_path, monkeypatch)
    wid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    CredentialStore(tmp_path, wid, _test_secrets={}).set_api_key("openai", "sk")
    prefs = WorkspacePreferences(
        llm=LLMPreferences(
            default_summarization="openai:gpt-test",
            default_chat="openai:gpt-other",
        ),
        memory=MemoryPreferences(summarization_llm_id="openai:gpt-other"),
    )
    r = resolve_summarization_llm(prefs, tmp_path)
    assert r is not None and r.model_id == "openai:gpt-other"
