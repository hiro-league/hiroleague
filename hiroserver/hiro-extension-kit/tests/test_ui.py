"""The built UI (ui.py): which file a path gets, and how long a browser may keep it."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hiro_extension_kit import ui


def _client(tmp_path, monkeypatch) -> TestClient:
    (tmp_path / "_app" / "immutable" / "entry").mkdir(parents=True)
    (tmp_path / "_app" / "immutable" / "entry" / "app.Bf_kakia.js").write_text("js")
    (tmp_path / "index.html").write_text("<html>home</html>")
    (tmp_path / "200.html").write_text("<html>spa</html>")
    monkeypatch.setattr(ui, "STATIC_DIR", tmp_path.resolve())
    app = FastAPI()
    app.include_router(ui.router)
    return TestClient(app)


def test_pages_are_asked_for_again_and_hashed_files_kept(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    page = client.get("/")
    assert page.text == "<html>home</html>" and page.headers["cache-control"] == "no-cache"
    spa = client.get("/people")
    assert spa.text == "<html>spa</html>" and spa.headers["cache-control"] == "no-cache"
    js = client.get("/_app/immutable/entry/app.Bf_kakia.js")
    assert js.text == "js" and js.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_cache_control_by_path():
    assert ui.cache_control("_app/immutable/nodes/2.kt9yyQLQ.js").endswith("immutable")
    assert ui.cache_control("_app/version.json") == "no-cache"
    assert ui.cache_control("index.html") == "no-cache"
