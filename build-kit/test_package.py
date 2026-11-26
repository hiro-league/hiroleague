"""package.py's own rules: what it reads from an app's lock and pyproject, and the core versions it writes.

The whole build (uv build, uv export, the app's own environment) isn't run here: it would need every library of the
test app in uv's cache, and the core's deploy runs this check on Simone. It was tried by hand on the PC (the test
app's package installed into a plain environment, its health and its UI answered).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from package import PackageError, command_of, constraints, core_range, local_packages  # noqa: E402

LOCK = """
version = 1

[[package]]
name = "example-hello"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "hiro-extension-kit"
version = "0.2.0"
source = { editable = "../../../hiroserver/hiro-extension-kit" }

[[package]]
name = "hiro-commons"
version = "0.2.0"
source = { directory = "../../../hiroserver/hiro-commons" }

[[package]]
name = "pydantic"
version = "2.13.0"
source = { registry = "https://pypi.org/simple" }
"""


def test_the_local_packages_are_the_kits_not_the_app_nor_pypis() -> None:
    assert local_packages(LOCK) == {
        "hiro-extension-kit": "../../../hiroserver/hiro-extension-kit",
        "hiro-commons": "../../../hiroserver/hiro-commons",
    }


def test_the_core_versions_follow_the_kits_release_line() -> None:
    assert core_range("0.2.0") == ">=0.2,<0.3"
    assert core_range("1.9.4") == ">=1.9,<1.10"
    with pytest.raises(PackageError, match="major.minor"):
        core_range("dev")


def test_the_command_is_the_apps_one_console_script() -> None:
    assert command_of({"scripts": {"example-hello": "hello.main:serve"}}) == "example-hello"
    with pytest.raises(PackageError, match="exactly one console script"):
        command_of({})
    with pytest.raises(PackageError, match="it has 2"):
        command_of({"scripts": {"a": "x:y", "b": "x:z"}})


def test_the_test_app_has_what_the_build_needs() -> None:
    app = Path(__file__).parent / "test-app"
    assert (app / "backend" / "uv.lock").is_file()
    assert (app / "frontend" / "build" / "index.html").is_file()
    assert "hiro-extension-kit" in local_packages((app / "backend" / "uv.lock").read_text(encoding="utf-8"))


def test_the_constraints_pin_pypis_versions_and_the_kits_never_the_app() -> None:
    exported = "# a comment\npydantic==2.13.0\ncolorama==0.4.6 ; sys_platform == 'win32'\n    # via click\n"
    pinned = constraints(LOCK, exported).splitlines()
    assert pinned == ["pydantic==2.13.0", "colorama==0.4.6 ; sys_platform == 'win32'", "hiro-commons==0.2.0",
                      "hiro-extension-kit==0.2.0"]
