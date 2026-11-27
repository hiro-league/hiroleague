"""`hiro upgrade`'s command (tools/server.py): a Linux install keeps its torch build across an upgrade."""

from __future__ import annotations

import sys
from importlib import metadata

from hirocli.tools import server


def _torch(monkeypatch, version: str | None) -> None:
    def fake(name: str) -> str:
        if name != "torch" or version is None:
            raise metadata.PackageNotFoundError(name)
        return version

    monkeypatch.setattr(server.metadata, "version", fake)


def test_a_linux_install_keeps_its_torch_build(monkeypatch) -> None:
    # uv's receipt doesn't remember the backend, and `uv tool upgrade` takes none: it would bring NVIDIA's torch back
    _torch(monkeypatch, "2.12.0+cpu")
    assert server.torch_backend("linux") == "cpu"
    _torch(monkeypatch, "2.12.0+cu130")
    assert server.torch_backend("linux") == "cu130"
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert server._build_upgrade_command("uv-tool-hiroleague", "cpu") == [
        "uv", "tool", "install", "--upgrade", "--reinstall", "--python", python, "--torch-backend", "cpu", "hiroleague"]


def test_pypi_s_own_build_and_other_systems_upgrade_as_before(monkeypatch) -> None:
    _torch(monkeypatch, "2.12.0")
    assert server.torch_backend("linux") is None
    assert server.torch_backend("win32") is None
    assert server._build_upgrade_command("uv-tool-hiroleague", None) == [
        "uv", "tool", "upgrade", "--reinstall", "hiroleague"]


def test_a_linux_install_without_torch_gets_the_processor_only_one(monkeypatch) -> None:
    _torch(monkeypatch, None)
    assert server.torch_backend("linux") == "cpu"
