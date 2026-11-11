"""The built admin's pages have no trailing slash (UI kit step 1d): /server is server.html."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hirocli.admin_svelte import static_server


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    (tmp_path / "index.html").write_text("dashboard", encoding="utf-8")
    (tmp_path / "server.html").write_text("server page", encoding="utf-8")
    (tmp_path / "_app").mkdir()
    (tmp_path / "_app" / "start.js").write_text("js", encoding="utf-8")
    monkeypatch.setattr(static_server, "admin_svelte_static_dir", lambda: tmp_path)
    app = FastAPI()

    @app.get("/api/ping")
    async def ping() -> dict[str, bool]:
        return {"pong": True}

    static_server.mount_admin_svelte_static(app)
    return TestClient(app, follow_redirects=False)


def test_the_dashboard_and_assets_are_served(client: TestClient) -> None:
    assert client.get("/").text == "dashboard"
    assert client.get("/_app/start.js").text == "js"
    assert client.get("/api/ping").json() == {"pong": True}


def test_a_page_is_served_at_its_address_without_a_slash(client: TestClient) -> None:
    response = client.get("/server?tab=workspaces")
    assert response.status_code == 200
    assert response.text == "server page"


def test_the_old_address_with_a_slash_is_sent_on_and_keeps_its_query(client: TestClient) -> None:
    response = client.get("/server/?tab=workspaces")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/server?tab=workspaces")


def test_an_unknown_path_is_still_a_404(client: TestClient) -> None:
    assert client.get("/nowhere").status_code == 404
    assert client.get("/nowhere/").status_code == 404
    assert client.get("/api/nowhere").status_code == 404
    assert client.get("/_app/missing.js").status_code == 404
