"""Phase 7a: models a local server reports — read, kept, and built without catalog rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hirocli.domain import discovered_models as dm
from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_factory import build_chat_model_from_tuning
from hirocli.domain.preferences import ModelTuning


class _FakeServer:
    """Stands in for the module's _get_json: canned answers by "METHOD url [model]"."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers

    def __call__(self, url: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
        return self.answers[f"{method} {url}" + (f" {body['model']}" if body else "")]


def test_ollama_lists_chat_models_with_pictures_and_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    base = "http://pc:11434"
    monkeypatch.setattr(
        dm,
        "_get_json",
        _FakeServer(
            {
                f"GET {base}/api/tags": {"models": [{"name": "qwen3-vl:8b"}, {"name": "nomic-embed-text"}]},
                f"GET {base}/api/ps": {"models": [{"name": "qwen3-vl:8b"}]},
                f"POST {base}/api/show qwen3-vl:8b": {"capabilities": ["completion", "vision", "thinking"]},
                f"POST {base}/api/show nomic-embed-text": {"capabilities": ["embedding"]},
            }
        ),
    )
    [model] = dm.probe_local_models("ollama", base + "/")
    assert (model.id, model.vision, model.reasoning, model.loaded) == ("ollama:qwen3-vl:8b", True, True, True)


def test_lm_studio_lists_llms_only(monkeypatch: pytest.MonkeyPatch) -> None:
    base = "http://pc:1234"
    monkeypatch.setattr(
        dm,
        "_get_json",
        _FakeServer(
            {
                f"GET {base}/api/v1/models": {
                    "models": [
                        {"type": "llm", "key": "gemma-4-12b", "display_name": "Gemma 4 12B", "capabilities": {"vision": True}},
                        {"type": "embedding", "key": "nomic"},
                    ]
                }
            }
        ),
    )
    [model] = dm.probe_local_models("lm_studio", base + "/v1")
    assert (model.id, model.display_name, model.vision, model.loaded) == ("lm_studio:gemma-4-12b", "Gemma 4 12B", True, False)


def test_an_unreachable_server_is_a_local_server_error() -> None:
    with pytest.raises(dm.LocalServerError):
        dm.probe_local_models("ollama", "http://127.0.0.1:9")


def test_kept_list_replaces_per_server_and_builds_without_a_catalog_row(tmp_path: Path) -> None:
    seen = dm.DiscoveredModel("lm_studio", "qwen3-vl-8b", "Qwen3 VL 8B", vision=True, reasoning=False, loaded=True)
    dm.save_discovered_models(tmp_path, "lm_studio", [seen])
    dm.save_discovered_models(tmp_path, "ollama", [dm.DiscoveredModel("ollama", "gemma4:e4b", "gemma4:e4b", False, True, False)])
    dm.save_discovered_models(tmp_path, "lm_studio", [seen])  # a second check replaces, never duplicates
    assert [m.id for m in dm.list_discovered_models(tmp_path)] == ["lm_studio:qwen3-vl-8b", "ollama:gemma4:e4b"]
    kept = dm.get_discovered_model(tmp_path, "lm_studio:qwen3-vl-8b")
    assert kept is not None and kept.seen_at

    spec = dm.discovered_model_spec(kept)
    assert spec.model_kind == "chat" and "image" in spec.modalities
    store = CredentialStore(tmp_path, "test-ws")
    store.set_local_endpoint("lm_studio", "http://192.168.1.90:1234")
    model = build_chat_model_from_tuning(
        spec.id, workspace_path=tmp_path, tuning=ModelTuning(), credential_store=store, spec=spec
    )
    # LM Studio's OpenAI-compatible API lives under /v1 (the stored endpoint is the server root).
    assert str(model.openai_api_base).endswith(":1234/v1")
    assert model.model_name == "qwen3-vl-8b"
