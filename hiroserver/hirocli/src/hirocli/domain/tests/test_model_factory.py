"""Tests for create_chat_model guard rails."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain.model_catalog import clear_model_catalog_cache
from hirocli.domain.model_factory import create_chat_model


@pytest.fixture(autouse=True)
def _clear_cat() -> None:
    clear_model_catalog_cache()
    yield
    clear_model_catalog_cache()


def _registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    from hirocli.domain import workspace as ws_mod

    wid = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"
    reg = ws_mod.WorkspaceRegistry(
        default_workspace=wid,
        workspaces={
            wid: ws_mod.WorkspaceEntry(
                id=wid,
                name="tf",
                path=str(tmp_path.resolve()),
                port_slot=0,
            ),
        },
    )
    monkeypatch.setattr(ws_mod, "load_registry", lambda: reg)
    return wid


def test_unknown_model_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _registry(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="Unknown model"):
        create_chat_model(
            "openai:definitely-not-in-catalog-xyz",
            workspace_path=tmp_path,
        )


def test_unconfigured_provider_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _registry(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="not configured"):
        create_chat_model(
            "openai:gpt-5.4",
            workspace_path=tmp_path,
        )
