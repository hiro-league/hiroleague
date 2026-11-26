"""A package (the app's wheel) as the core reads it (domain/packages.py), the Hiro home's layout (domain/hiro_home.py), and the
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
    pins,
    service_name,
    version_in,
    wheel_name,
)

MANIFEST = """key = "example.hello"
kind = "app"
title = "Hello"
version = "0.1.0"
core = ">=0.2,<0.3"
command = "example-hello"
port = 8190
"""


CONSTRAINTS = "fastapi==1.0 ; python_version >= '3.12'\nhiro-extension-kit==0.2.0\nhiro_commons==0.2.0\n"
WHEEL = "example_hello-0.1.0-py3-none-any.whl"


def make_package(tmp_path: Path, *, manifest: str = MANIFEST, name: str = WHEEL,
                 members: dict[str, str] | None = None) -> Path:
    """An app's wheel as package.py builds it: its manifest and its pins in its module's folder."""
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("hello/__init__.py", "")
        if manifest:
            zf.writestr("hello/hiro-extension.toml", manifest)
        zf.writestr("hello/hiro-constraints.txt", CONSTRAINTS)
        for member, text in (members or {}).items():
            zf.writestr(member, text)
    return path


def library(folder: Path, name: str) -> Path:
    path = folder / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("lib/__init__.py", "")
    return path


def test_a_package_is_the_apps_wheel_with_its_manifest_its_pins_and_its_kits_beside_it(tmp_path: Path) -> None:
    kit = library(tmp_path, "hiro_extension_kit-0.2.0-py3-none-any.whl")
    commons = library(tmp_path, "hiro_commons-0.2.0-py3-none-any.whl")
    library(tmp_path, "hiro_commons-0.1.0-py3-none-any.whl")  # not the version it pins
    library(tmp_path, "requests-2.0-py3-none-any.whl")  # not one of its pins
    package = open_package(make_package(tmp_path))
    assert package.manifest.key == "example.hello"
    assert "fastapi==1.0" in package.constraints
    assert package.libraries == (commons, kit)


def test_pins_and_wheel_names_are_read_as_pypi_compares_names() -> None:
    assert pins(CONSTRAINTS) == {"fastapi": "1.0", "hiro-extension-kit": "0.2.0", "hiro-commons": "0.2.0"}
    assert wheel_name("Hiro_Extension.Kit-0.2.0-py3-none-any.whl") == ("hiro-extension-kit", "0.2.0")
    assert wheel_name("neonize-0.5.2-1-py3-none-win_amd64.whl") == ("neonize", "0.5.2")
    assert wheel_name("hello.zip") is None


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"manifest": ""}, "no hiro-extension.toml"),
        ({"manifest": MANIFEST.replace('kind = "app"', 'kind = "plugin"')}, "kind"),
        ({"members": {"other/hiro-extension.toml": MANIFEST}}, "no hiro-extension.toml"),  # two: neither is its own
        ({"name": "example-hello-0.1.0.zip"}, "isn't a wheel"),
    ],
)
def test_a_bad_package_is_refused_as_bad_manifest(tmp_path: Path, kwargs: dict, words: str) -> None:
    with pytest.raises(PackageRefused, match=words) as e:
        open_package(make_package(tmp_path, **kwargs))
    assert e.value.code == BAD_MANIFEST


def test_a_file_that_isnt_a_wheel_is_refused(tmp_path: Path) -> None:
    path = tmp_path / WHEEL
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
