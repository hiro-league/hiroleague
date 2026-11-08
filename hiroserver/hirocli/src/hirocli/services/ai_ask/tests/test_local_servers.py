"""Phase 7a Part B: loading before an ask and unloading idle models on local servers (fake server calls)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from hirocli.domain.preferences import LocalServerSettings
from hirocli.services.ai_ask import local_servers as ls


class FakeServer:
    """Stands in for ``local_servers._call``: LM Studio's REST answers, and every call seen."""

    def __init__(self, loaded: dict[str, dict[str, int]] | None = None) -> None:
        self.loaded = dict(loaded or {})  # model → its config
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def __call__(self, label: str, method: str, url: str, timeout: float, body: dict[str, Any] | None = None) -> Any:
        path = url.split(":1234", 1)[-1].split(":11434", 1)[-1]
        self.calls.append((method, path, body))
        if path == "/api/v1/models":
            return {
                "models": [
                    {"key": key, "type": "llm", "loaded_instances": [{"id": key, "config": cfg}] if key in self.loaded else []}
                    for key, cfg in (("qwen3-vl-8b", self.loaded.get("qwen3-vl-8b", {})), ("gemma-4-12b", self.loaded.get("gemma-4-12b", {})))
                ]
            }
        if path == "/api/v1/models/load":
            self.loaded[body["model"]] = {"context_length": body["context_length"], "physical_batch_size": body["physical_batch_size"]}
        if path == "/api/v1/models/unload":
            self.loaded.pop(body["instance_id"], None)
        return {}


@pytest.fixture(autouse=True)
def _clean() -> Any:
    ls.forget_all()
    yield
    ls.forget_all()


def _paths(server: FakeServer, method: str) -> list[str]:
    return [p for m, p, _ in server.calls if m == method]


def test_lm_studio_loads_with_the_settings_and_makes_room_for_another_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer()
    monkeypatch.setattr(ls, "_call", server)
    settings = LocalServerSettings(context=8192, batch=2048)

    asyncio.run(ls.prepare(tmp_path, "lm_studio", "qwen3-vl-8b", settings, context=None, store=None))
    assert server.loaded["qwen3-vl-8b"] == {"context_length": 8192, "physical_batch_size": 2048}
    assert list(ls.loaded_by_core(tmp_path, "lm_studio")) == ["qwen3-vl-8b"]

    # Another model: the core's earlier one is unloaded first (one of ours at a time on a home GPU).
    asyncio.run(ls.prepare(tmp_path, "lm_studio", "gemma-4-12b", settings, context=16384, store=None))
    assert "qwen3-vl-8b" not in server.loaded and server.loaded["gemma-4-12b"]["context_length"] == 16384
    assert list(ls.loaded_by_core(tmp_path, "lm_studio")) == ["gemma-4-12b"]


def test_a_model_loaded_by_hand_with_enough_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer({"qwen3-vl-8b": {"context_length": 32768, "physical_batch_size": 4096}})
    monkeypatch.setattr(ls, "_call", server)
    asyncio.run(ls.prepare(tmp_path, "lm_studio", "qwen3-vl-8b", LocalServerSettings(), context=None, store=None))
    assert "/api/v1/models/load" not in _paths(server, "POST")
    assert ls.loaded_by_core(tmp_path, "lm_studio") == {}  # not ours to unload


def test_idle_models_are_unloaded_after_the_servers_minutes_and_busy_servers_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = FakeServer()
    monkeypatch.setattr(ls, "_call", server)
    asyncio.run(ls.prepare(tmp_path, "lm_studio", "qwen3-vl-8b", LocalServerSettings(), context=None, store=None))
    asyncio.run(ls.prepare(tmp_path, "ollama", "gemma4:e4b", LocalServerSettings(), context=None, store=None))
    settings = {"lm_studio": LocalServerSettings(unload_idle_min=5), "ollama": LocalServerSettings(unload_idle_min=5)}

    assert asyncio.run(ls.unload_idle(tmp_path, settings, set(), None)) == []  # not idle yet
    for key in list(ls._loaded_by_core):
        ls._loaded_by_core[key] -= 6 * 60  # six minutes ago
    assert asyncio.run(ls.unload_idle(tmp_path, settings, {"ollama"}, None)) == ["lm_studio:qwen3-vl-8b"]
    done = asyncio.run(ls.unload_idle(tmp_path, settings, set(), None))
    assert done == ["ollama:gemma4:e4b"]
    assert ("POST", "/api/generate", {"model": "gemma4:e4b", "keep_alive": 0}) in server.calls
