"""The Extensions page's installed apps (admin_svelte/routes/installs.py): the packages waiting in the Hiro home and
what each offers, what each connected app still needs set, start and stop, and an upgrade run as a job."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hiro_channel_sdk.extension import ExtensionRequestError
from hiro_channel_sdk.manifest import Manifest, render_manifest
from hirocli.admin_svelte.routes import installs as routes
from hirocli.domain.packages import PackageRefused, stored_package


def _package(folder: Path, version: str, key: str = "example.hello") -> Path:
    m = Manifest(key=key, kind="app", title="Hello", version=version, core=">=0.0", command="example-hello",
                 port=8190)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("hello/hiro-extension.toml", render_manifest(m))
        zf.writestr("hello/hiro-constraints.txt", "hiro-commons==0.2.0\n")
    path = folder / f"{key.replace('.', '_')}-{version}-py3-none-any.whl"
    path.write_bytes(buffer.getvalue())
    return path


def _library(folder: Path, name: str = "hiro_commons", version: str = "0.2.0") -> Path:
    """A kit's wheel beside the app's: no manifest."""
    path = folder / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{name}/__init__.py", "")
    return path


def test_each_package_offers_an_install_an_upgrade_or_nothing(tmp_path: Path) -> None:
    _package(tmp_path, "0.1.1")
    _package(tmp_path, "0.2.0", key="acme.notes")
    _package(tmp_path, "0.0.9", key="acme.old")
    _library(tmp_path)  # a kit's wheel: no package of its own, never refused
    (tmp_path / "broken-0.1.0-py3-none-any.whl").write_text("not a wheel")
    found = routes.read_packages(tmp_path, {"example.hello": "0.1.0", "acme.old": "0.1.0"})
    assert {p.key: p.offer for p in found.packages} == {"example.hello": "upgrade", "acme.notes": "install",
                                                        "acme.old": "none"}
    assert "acme_notes-0.2.0-py3-none-any.whl" in next(p.command for p in found.packages if p.key == "acme.notes")
    assert list(found.refused) == ["broken-0.1.0-py3-none-any.whl"]
    assert routes.read_packages(tmp_path / "none", {}).packages == []


def test_an_upgrade_takes_only_a_package_of_that_folder(tmp_path: Path) -> None:
    folder, ws = tmp_path / "packages", tmp_path / "ws"
    folder.mkdir()
    ws.mkdir()
    _package(folder, "0.1.1")
    _library(folder)
    _library(folder, "hiro_memory")  # beside it, but no pin of the app's: left alone
    package_id = routes.hand_over(folder, "example_hello-0.1.1-py3-none-any.whl", ws)
    wheel = stored_package(ws, package_id)
    assert sorted(p.name for p in wheel.parent.iterdir()) == ["example_hello-0.1.1-py3-none-any.whl",
                                                              "hiro_commons-0.2.0-py3-none-any.whl"]
    (tmp_path / "outside-0.1.0-py3-none-any.whl").write_text("x")
    for bad in ("../outside-0.1.0-py3-none-any.whl", "missing-0.1.0-py3-none-any.whl"):
        with pytest.raises(PackageRefused):
            routes.hand_over(folder, bad, ws)


class _Manager:
    """Three connected apps: one with something left to set, one from before setup, one whose answer fails."""

    def snapshot(self, kind: str | None = "app") -> dict[str, Any]:
        return {"id-hello": {"name": "example.hello"}, "id-old": {"name": "net"}, "id-away": {"name": "home"}}

    async def request(self, extension_id: str, method: str, params: dict, timeout: float) -> dict[str, Any]:
        if extension_id == "id-old":
            raise ExtensionRequestError("method_not_found", "unknown method")
        if extension_id == "id-away":
            raise ExtensionRequestError("not_connected", "Home isn't connected.")
        return {"items": [
            {"id": "greeting", "title": "Write its greeting", "done": False, "link": {"app": "example.hello", "path": "/"}},
            {"id": "who", "title": "Pick who it greets", "done": True, "link": {"app": "example.hello", "path": "/"}},
        ]}


def test_setup_lists_only_whats_left_and_an_app_from_before_has_nothing(monkeypatch, tmp_path: Path) -> None:
    from hirocli.admin_svelte.routes import extensions

    monkeypatch.setattr(extensions, "_live_manager", lambda request, path: _Manager())
    monkeypatch.setattr(routes.ExtensionService, "workspace_path", lambda self, wid: tmp_path)
    answer = asyncio.run(routes.list_setup(SimpleNamespace(), "ws"))
    assert answer["left"] == {"id-hello": [routes.SetupLeft(title="Write its greeting", app="example.hello", path="/")],
                              "id-old": []}
    assert answer["errors"] == {"id-away": "Home isn't connected."}


def test_start_and_stop_answer_the_tools_words(monkeypatch) -> None:
    def refused(**kw: Any) -> Any:
        return SimpleNamespace(refused="upgrading", words="Hello is upgrading.", step="")

    monkeypatch.setattr(routes.ExtensionStopTool, "execute", lambda self, **kw: refused(**kw))
    answer = asyncio.run(routes.stop_install("example.hello", "ws"))
    assert answer.status_code == 409 and json.loads(answer.body)["detail"] == "Hello is upgrading."
    monkeypatch.setattr(routes.ExtensionStartTool, "execute",
                        lambda self, **kw: SimpleNamespace(refused="", words="", step="started"))
    assert asyncio.run(routes.start_install("example.hello", "ws")) == {"key": "example.hello", "step": "started"}


def test_an_upgrade_runs_as_a_job_the_page_follows_to_its_end(monkeypatch, tmp_path: Path) -> None:
    folder = tmp_path / "packages"
    folder.mkdir()
    _package(folder, "0.1.1")
    monkeypatch.setattr(routes, "packages_folder", lambda: folder)
    monkeypatch.setattr(routes.ExtensionService, "workspace_path", lambda self, wid: tmp_path)
    ran: list[str] = []

    def upgrade(self, key: str, package: str, workspace: str | None = None, allow_row_loss=None) -> Any:
        ran.append(package)
        return SimpleNamespace(key=key, title="Hello", before="0.1.0", to="0.1.1", outcome="upgraded",
                               words="Hello runs 0.1.1.", new_asks=[])

    monkeypatch.setattr(routes.ExtensionUpgradeTool, "execute", upgrade)
    monkeypatch.setattr(routes, "asdict", lambda done: dict(vars(done)))
    routes._UPGRADES.clear()

    async def scenario() -> dict[str, Any]:
        started = await routes.start_upgrade("example.hello", routes.UpgradeBody(file="example_hello-0.1.1-py3-none-any.whl"), "ws")
        assert started["running"] is True
        again = await routes.start_upgrade("example.hello", routes.UpgradeBody(file="example_hello-0.1.1-py3-none-any.whl"), "ws")
        assert again.status_code == 409
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not routes._UPGRADES["example.hello"]["running"]:
                break
        return await routes.upgrade_state("example.hello")

    state = asyncio.run(scenario())
    assert (state["running"], state["outcome"], state["to"]) == (False, "upgraded", "0.1.1")
    assert len(ran) == 1 and stored_package(tmp_path, ran[0]).is_file()
