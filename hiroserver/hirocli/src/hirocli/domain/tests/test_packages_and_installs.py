"""A package as the core reads it (domain/packages.py), the Hiro home's layout (domain/hiro_home.py), and the
installs store (domain/installs.py)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from hirocli.domain import installs
from hirocli.domain.hiro_home import ENV_HIRO_HOME, app_folder, default_home, hiro_home
from hirocli.domain.packages import (
    BAD_MANIFEST,
    PackageRefused,
    open_package,
    service_name,
    version_in,
)

MANIFEST = """key = "example.hello"
kind = "app"
title = "Hello"
version = "0.1.0"
core = ">=0.2,<0.3"
command = "example-hello"
port = 8190
"""


def make_package(tmp_path: Path, *, manifest: str = MANIFEST, members: dict[str, str] | None = None) -> Path:
    path = tmp_path / "example-hello-0.1.0.zip"
    with zipfile.ZipFile(path, "w") as zf:
        if manifest:
            zf.writestr("hiro-extension.toml", manifest)
        zf.writestr("requirements.txt", "fastapi==1.0 --hash=sha256:00\n")
        for name, text in (members or {"wheels/example_hello-0.1.0-py3-none-any.whl": "x"}).items():
            zf.writestr(name, text)
    return path


def test_a_package_is_read_with_its_manifest_wheels_and_requirements(tmp_path: Path) -> None:
    package = open_package(make_package(tmp_path))
    assert package.manifest.key == "example.hello"
    assert package.wheels == ("wheels/example_hello-0.1.0-py3-none-any.whl",)
    assert "fastapi==1.0" in package.requirements


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"manifest": ""}, "no hiro-extension.toml"),
        ({"manifest": MANIFEST.replace('kind = "app"', 'kind = "plugin"')}, "kind"),
        ({"members": {"wheels/../../evil.whl": "x"}}, "outside its own folder"),
        ({"members": {"notes.txt": "x"}}, "holds no wheel"),
    ],
)
def test_a_bad_package_is_refused_as_bad_manifest(tmp_path: Path, kwargs: dict, words: str) -> None:
    with pytest.raises(PackageRefused, match=words) as e:
        open_package(make_package(tmp_path, **kwargs))
    assert e.value.code == BAD_MANIFEST


def test_a_file_that_isnt_a_zip_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "x.zip"
    path.write_text("not a zip")
    with pytest.raises(PackageRefused, match="can't be read"):
        open_package(path)


@pytest.mark.parametrize(
    ("versions", "version", "ok"),
    [
        (">=0.2,<0.3", "0.2.0", True),
        (">=0.2,<0.3", "0.2.9", True),
        (">=0.2,<0.3", "0.3.0", False),
        (">=0.2,<0.3", "0.1.9", False),
        ("==0.2.0", "0.2.0", True),
        ("~=0.2", "0.9.1", True),
        ("~=0.2", "1.0.0", False),
        ("soon", "0.2.0", False),
    ],
)
def test_the_core_version_range(versions: str, version: str, ok: bool) -> None:
    assert version_in(versions, version) is ok


def test_an_apps_service_and_account_are_its_dashed_key() -> None:
    assert service_name("example.hello") == "hiro-example-hello"
    assert service_name("home") == "hiro-home"


def test_the_hiro_home_is_the_systems_or_the_one_named(monkeypatch, tmp_path: Path) -> None:
    assert default_home("linux") == Path("/opt/hiroleague")
    assert default_home("darwin") == Path("/Library/Application Support/HiroLeague")
    monkeypatch.setenv(ENV_HIRO_HOME, str(tmp_path))
    assert hiro_home() == tmp_path
    app = app_folder("example.hello")
    assert app.root == tmp_path / "apps" / "example.hello"
    assert (app.release("0.1.0"), app.data) == (app.root / "releases" / "0.1.0", app.root / "data")


def test_an_install_keeps_only_its_codes_hash_and_finds_it_by_the_code(tmp_path: Path) -> None:
    code = installs.new_code()
    assert len(code) >= 30
    row = installs.add_install(tmp_path, key="example.hello", kind="app", title="Hello", version="0.1.0", port=8190,
                               service="hiro-example-hello", account="hiro-example-hello", home=str(tmp_path),
                               code=code)
    assert row.state == installs.APPROVING
    assert installs.install_for_code(tmp_path, code).key == "example.hello"
    assert installs.install_for_code(tmp_path, "guess") is None
    installs.code_used(tmp_path, "example.hello")
    assert installs.install_for_code(tmp_path, code) is None
    assert installs.get_install(tmp_path, "example.hello").state == installs.RUNNING


def test_one_install_per_key_and_per_port(tmp_path: Path) -> None:
    common = {"kind": "app", "title": "Hello", "version": "0.1.0", "service": "s", "account": "a", "home": "h",
              "code": "c"}
    installs.add_install(tmp_path, key="example.hello", port=8190, **common)
    with pytest.raises(installs.InstallExists):
        installs.add_install(tmp_path, key="example.hello", port=8191, **common)
    with pytest.raises(installs.InstallExists, match="8190"):
        installs.add_install(tmp_path, key="example.other", port=8190, **common)
    assert installs.remove_install(tmp_path, "example.hello") is True
    assert installs.list_installs(tmp_path) == []
