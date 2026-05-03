"""Phase 6 — public character profile routes on the main HTTP app."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hirocli.domain.character import seed_default_characters
from hirocli.runtime import http_server


class _FakeCtx:
    __slots__ = ("workspace_path",)

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    seed_default_characters(tmp_path)
    fake = _FakeCtx(tmp_path)
    monkeypatch.setattr(http_server, "_ctx", lambda _request: fake)
    return TestClient(http_server.app)


def test_list_characters(client: TestClient) -> None:
    r = client.get("/characters")
    assert r.status_code == 200
    data = r.json()
    assert "characters" in data
    ids = {c["id"] for c in data["characters"]}
    assert "hiro" in ids
    hiro = next(c for c in data["characters"] if c["id"] == "hiro")
    assert "name" in hiro
    assert "description" in hiro
    assert "has_photo" in hiro
    assert "llm_models" in hiro
    assert "voice_models" in hiro


def test_character_profile(client: TestClient) -> None:
    r = client.get("/characters/hiro/profile")
    assert r.status_code == 200
    p = r.json()
    assert p["id"] == "hiro"
    assert p["name"]
    assert "description" in p
    assert "has_photo" in p
    assert "llm_models" in p and isinstance(p["llm_models"], list)
    assert "voice_models" in p and isinstance(p["voice_models"], list)


def test_character_profile_unknown(client: TestClient) -> None:
    r = client.get("/characters/no-such-slug/profile")
    assert r.status_code == 404


def test_character_photo_serves_bytes(client: TestClient) -> None:
    r = client.get("/characters/hiro/photo")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("image/")
    assert len(r.content) > 0


def test_character_photo_unknown(client: TestClient) -> None:
    r = client.get("/characters/unknown-face/photo")
    assert r.status_code == 404
