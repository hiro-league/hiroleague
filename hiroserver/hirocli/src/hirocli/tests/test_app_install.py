"""Installing an app, the core's own steps (services/app_install.py) and what the person approves
(domain/install_consent.py). The system is faked: nothing here makes an account, a service or a venv."""

from __future__ import annotations

import io
import socket
import sys
import zipfile
from pathlib import Path

import pytest

from hiro_channel_sdk.approvals import PEOPLE_NOTIFY, PEOPLE_SEE, SITE_ADDRESS, SITE_NAME, AppAsk, ApprovedItem
from hiro_channel_sdk.manifest import Manifest, render_manifest
from hirocli import app_system
from hirocli.domain import installs
from hirocli.domain.config import Config, save_config
from hirocli.domain.hiro_home import ENV_HIRO_HOME, app_folder
from hirocli.domain.install_consent import at_pairing, consent, sheet, site_of
from hirocli.domain.packages import (
    CORE_VERSION,
    NAME_TAKEN,
    PORT_TAKEN,
    PackageRefused,
    drop_package,
    keep_package,
    prune_packages,
    stored_package,
)
from hirocli.services import app_install

ASKS = (
    AppAsk(permission=PEOPLE_SEE, why="It greets people by name"),
    AppAsk(permission=PEOPLE_NOTIFY, required=False, why="It can say hello"),
    AppAsk(permission="weather.read", why="Not a permission this core knows"),
)


def manifest(**change) -> Manifest:
    fields = {"key": "example.hello", "kind": "app", "title": "Hello", "version": "0.1.0", "core": ">=0.0",
              "command": "example-hello", "port": _free_port(), "asks": ASKS}
    return Manifest(**{**fields, **change})


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def package_bytes(m: Manifest) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("hiro-extension.toml", render_manifest(m))
        zf.writestr("requirements.txt", "")
        zf.writestr("wheels/example_hello-0.1.0-py3-none-any.whl", "x")
    return buffer.getvalue()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    # The core's ports are only numbers here (nothing listens): fixed, apart from the free ports an app takes
    save_config(ws, Config(extension_host="0.0.0.0", http_port=7491, admin_port=7492, extension_port=7493))  # noqa: S104
    monkeypatch.setenv(ENV_HIRO_HOME, str(tmp_path / "home"))
    return ws


# ---------------------------------------------------------------------------
# What the person approves
# ---------------------------------------------------------------------------


def test_the_sheet_holds_its_asks_its_address_and_its_name_for_its_port() -> None:
    m = manifest(port=8190)
    items = sheet(m, "hiro.local", 8190)
    assert [(a.permission, a.subject, a.required) for a in items] == [
        (PEOPLE_SEE, "", True), (PEOPLE_NOTIFY, "", False), ("weather.read", "", True),
        (SITE_ADDRESS, "http://example-hello.hiro.local", True), (SITE_NAME, "example-hello.hiro.local:8190", True),
    ]
    assert items[0].words.startswith("read the people list")
    assert site_of(manifest(site="http://homehiro.local"), "hiro.local") == ("http://homehiro.local", "homehiro.local")


def test_the_yes_approves_what_is_required_and_understood_and_the_optional_ones_only_when_chosen() -> None:
    items = sheet(manifest(port=8190), "hiro.local", 8190)
    keys = {(i.permission, i.subject) for i in consent(items, set())}
    assert (PEOPLE_SEE, "") in keys and (SITE_NAME, "example-hello.hiro.local:8190") in keys
    assert (PEOPLE_NOTIFY, "") not in keys
    assert ("weather.read", "") not in keys  # not understood: never approved
    assert (PEOPLE_NOTIFY, "") in {(i.permission, i.subject) for i in consent(items, None)}


def test_at_pairing_it_is_approved_for_what_it_still_asks_and_its_name_before_it_claims_it() -> None:
    agreed = [ApprovedItem(permission=PEOPLE_SEE), ApprovedItem(permission=PEOPLE_NOTIFY),
              ApprovedItem(permission=SITE_NAME, subject="example-hello.hiro.local:8190")]
    info = {"asks": [{"permission": PEOPLE_SEE}], "offers": {"shows": []}}
    assert at_pairing(agreed, info) == [agreed[0], agreed[2]]


# ---------------------------------------------------------------------------
# The package store and the checks
# ---------------------------------------------------------------------------


def test_a_package_is_kept_by_its_hash_and_found_only_by_it(workspace: Path) -> None:
    package_id = keep_package(workspace, [b"abc", b"def"])
    assert len(package_id) == 64 and stored_package(workspace, package_id).read_bytes() == b"abcdef"
    for bad in ("../../etc/passwd", "a" * 64):
        with pytest.raises(PackageRefused):
            stored_package(workspace, bad)
    drop_package(workspace, package_id)
    with pytest.raises(PackageRefused, match="isn't kept"):
        stored_package(workspace, package_id)


def test_a_package_no_install_names_goes_after_a_day(workspace: Path) -> None:
    import os

    kept, old, named = (keep_package(workspace, [x]) for x in (b"new", b"old", b"named"))
    for package_id in (old, named):
        path = stored_package(workspace, package_id)
        os.utime(path, (path.stat().st_atime - 2 * 86400, path.stat().st_mtime - 2 * 86400))
    assert prune_packages(workspace, {named}) == 1
    stored_package(workspace, kept), stored_package(workspace, named)
    with pytest.raises(PackageRefused):
        stored_package(workspace, old)


def test_the_checks_refuse_with_their_codes(workspace: Path) -> None:
    from hirocli.domain.config import load_config

    config = load_config(workspace)
    app_install.check(workspace, manifest(), config)  # passes
    for m, code in [(manifest(key="weather"), NAME_TAKEN), (manifest(key="hiro.evil"), NAME_TAKEN),
                    (manifest(core=">=99"), CORE_VERSION), (manifest(port=config.admin_port), PORT_TAKEN)]:
        with pytest.raises(PackageRefused) as e:
            app_install.check(workspace, m, config)
        assert e.value.code == code
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        with pytest.raises(PackageRefused, match="already listens"):
            app_install.check(workspace, manifest(port=busy.getsockname()[1]), config)


# ---------------------------------------------------------------------------
# Prepare, cancel, finish, forget (the system faked)
# ---------------------------------------------------------------------------


def _prepared(workspace: Path, m: Manifest | None = None, chosen=frozenset()):
    package_id = keep_package(workspace, [package_bytes(m or manifest())])
    return app_install.prepare(workspace, package_id, set(chosen)), package_id


def test_prepare_keeps_the_yes_and_answers_the_job_and_a_declined_step_forgets_it(workspace: Path,
                                                                                    monkeypatch) -> None:
    (row, job), package_id = _prepared(workspace)
    assert row.state == installs.APPROVING and row.command == "example-hello" and row.package == package_id
    assert {i.permission for i in row.consent} == {PEOPLE_SEE, SITE_ADDRESS, SITE_NAME}
    assert job.model_dump() == {"action": "install", "key": "example.hello", "command": "example-hello",
                                "purge": False}
    monkeypatch.setattr(app_system, "is_running", lambda service: False)  # its admin step made the service
    with pytest.raises(PackageRefused, match="installed already"):
        _prepared(workspace)
    monkeypatch.setattr(app_system, "is_running", lambda service: None)  # declined: nothing made
    assert app_install.cancel(workspace, "example.hello") is True
    assert installs.get_install(workspace, "example.hello") is None
    with pytest.raises(PackageRefused):
        stored_package(workspace, package_id)


class _System:
    """The faked system: whether the admin step made the service, and what the core started."""

    def __init__(self, monkeypatch, *, made: bool = True, uv_fails: bool = False) -> None:
        self.started: list[str] = []
        self.environments: list[dict[str, str]] = []
        monkeypatch.setattr(app_system, "is_running", lambda service: False if made else None)
        monkeypatch.setattr(app_system, "start", self.started.append)
        monkeypatch.setattr(app_system, "write_windows_environment", lambda app, env: self.environments.append(env))

        def unpack(package, folder, workspace_path):
            if uv_fails:
                raise app_install.InstallFailed("Installing the app's libraries failed: no network.")
            release = folder.release(package.manifest.version)
            release.mkdir(parents=True)
            return release

        monkeypatch.setattr(app_install, "unpack", unpack)


def test_finish_unpacks_writes_its_environment_with_a_code_and_starts_it(workspace: Path, monkeypatch) -> None:
    system = _System(monkeypatch)
    (row, _), package_id = _prepared(workspace)
    done = app_install.finish(workspace, row.key)
    assert done.state == installs.WAITING and system.started == ["hiro-example-hello"]
    folder = app_folder(row.key)
    assert folder.current.resolve() == folder.release("0.1.0").resolve()
    if sys.platform == "win32":
        [env] = system.environments
    else:
        env = dict(line.split("=", 1) for line in folder.env_file.read_text().splitlines())
        env = {k: v.strip('"') for k, v in env.items()}
    assert env["PORT"] == str(row.port) and env["HIRO_CORE_URL"].startswith("ws://127.0.0.1:")
    assert installs.install_for_code(workspace, env["HIRO_PAIRING_CODE"]).key == row.key
    with pytest.raises(PackageRefused):  # unpacked: the package goes
        stored_package(workspace, package_id)


def test_finish_needs_the_admin_step_and_a_failed_step_leaves_words_and_can_be_removed(workspace: Path,
                                                                                         monkeypatch) -> None:
    _System(monkeypatch, made=False)
    (row, _), _ = _prepared(workspace)
    with pytest.raises(app_install.InstallFailed, match="admin step"):
        app_install.finish(workspace, row.key)
    assert installs.get_install(workspace, row.key).state == installs.APPROVING  # nothing was tried

    _System(monkeypatch, uv_fails=True)
    with pytest.raises(app_install.InstallFailed, match="no network"):
        app_install.finish(workspace, row.key)
    failed = installs.get_install(workspace, row.key)
    assert failed.state == installs.FAILED and "no network" in failed.step
    assert app_install.forget(workspace, row.key) is not None
    assert installs.get_install(workspace, row.key) is None


def test_forget_drops_the_releases_and_the_old_key_and_keeps_the_apps_data(workspace: Path, monkeypatch) -> None:
    _System(monkeypatch)
    (row, _), _ = _prepared(workspace)
    app_install.finish(workspace, row.key)
    folder = app_folder(row.key)
    (folder.data / "hiroleague").mkdir(parents=True)
    (folder.data / "hiroleague" / "key").write_text("old")
    (folder.data / "hello.db").write_text("the app's own")
    app_install.forget(workspace, row.key)
    assert not folder.releases.exists() and not folder.current.exists() and not (folder.data / "hiroleague").exists()
    assert (folder.data / "hello.db").read_text() == "the app's own"


def test_the_environment_file_refuses_a_value_it_cant_write_safely() -> None:
    assert app_install.render_env_file({"PORT": "8190"}) == 'PORT="8190"\n'
    with pytest.raises(app_install.InstallFailed):
        app_install.render_env_file({"DATA_DIR": 'C:\\a"b'})


def test_with_no_one_to_ask_only_approve_says_yes(monkeypatch) -> None:
    from rich.console import Console

    from hirocli.commands import extension_install as cli

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(cli._Stop, match="--approve"):
        cli._consent(Console(), approve=False)
    cli._consent(Console(), approve=True)  # consent given in advance


def test_an_install_stopped_after_its_service_was_made_stays_failed_to_remove(workspace: Path, monkeypatch) -> None:
    _System(monkeypatch, made=True)
    (row, _), package_id = _prepared(workspace)
    assert app_install.cancel(workspace, row.key) is False
    kept = installs.get_install(workspace, row.key)
    assert kept.state == installs.FAILED and "remove it" in kept.step
    stored_package(workspace, package_id)  # kept with the row until it is removed


# ---------------------------------------------------------------------------
# Its stories and lines (logs.md: a named story is tested with its title; a failure's line with its level)
# ---------------------------------------------------------------------------


def _lines(caplog) -> list[tuple[int, str, dict]]:
    from hiro_commons.logging_foundation.line import ATTRIBUTES

    return [(r.levelno, r.getMessage(), getattr(r, ATTRIBUTES, {}) or {}) for r in caplog.records]


def test_the_finish_is_the_install_story_and_says_the_yes_and_how(workspace: Path, monkeypatch, caplog) -> None:
    import logging

    from hirocli.tools import extension_install as tools

    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(tools, "_resolve_path", lambda workspace: workspace_path)
    workspace_path = workspace
    _System(monkeypatch)
    package_id = keep_package(workspace, [package_bytes(manifest())])
    tools.ExtensionInstallPrepareTool().execute(package=package_id, in_advance=True)
    result = tools.ExtensionInstallFinishTool().execute(key="example.hello")
    assert result.state == installs.WAITING
    lines = _lines(caplog)
    named = [a for _, _, a in lines if a.get("story.name") == "core.extension_install"]
    assert named and named[0]["story.title"] == "Hello installed"
    said = [m for _, m, _ in lines if m.startswith("Install: Hello 0.1.0, approved in advance (--approve): people.see")]
    assert said


def test_a_failed_finish_is_a_warning_with_its_key_and_the_remove_is_its_own_story(workspace: Path, monkeypatch,
                                                                                    caplog) -> None:
    import logging

    from hirocli.tools import extension_install as tools

    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(tools, "_resolve_path", lambda workspace: workspace_path)
    workspace_path = workspace
    _System(monkeypatch, uv_fails=True)
    (row, _), _ = _prepared(workspace)
    result = tools.ExtensionInstallFinishTool().execute(key=row.key)
    assert result.refused == "failed" and "no network" in result.words
    [warning] = [(level, a) for level, m, a in _lines(caplog) if m.startswith("⚠️ Install failed — Hello")]
    assert warning[0] == logging.WARNING and warning[1]["key"] == "example.hello"

    caplog.clear()
    forgotten = tools.ExtensionInstallForgetTool().execute(key=row.key)
    assert forgotten.forgotten is True
    named = [a for _, _, a in _lines(caplog) if a.get("story.name") == "core.extension_remove"]
    assert named and named[0]["story.title"] == "Hello removed"


def test_an_install_left_approving_with_nothing_made_doesnt_block_the_next_try(workspace: Path, monkeypatch) -> None:
    _System(monkeypatch, made=False)
    (row, _), _ = _prepared(workspace)  # its CLI closed before the admin step made anything
    (again, _), _ = _prepared(workspace)
    assert again.key == row.key and again.state == installs.APPROVING


def test_once_it_paired_its_step_is_clear(workspace: Path, monkeypatch) -> None:
    _System(monkeypatch)
    (row, _), _ = _prepared(workspace)
    app_install.finish(workspace, row.key)
    installs.code_used(workspace, row.key)
    done = installs.get_install(workspace, row.key)
    assert (done.state, done.step) == (installs.RUNNING, "")
