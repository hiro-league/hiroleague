"""Upgrading an installed app (services/app_upgrade.py). The system, the app's predeploy steps and its health are
faked: what is checked is the order of the steps, what is recorded, what is put back, and what a restart does."""

from __future__ import annotations

import io
import logging
import os
import zipfile
from pathlib import Path

import pytest

from hiro_channel_sdk.manifest import MANIFEST_FILE, Manifest, render_manifest
from hirocli import app_system
from hirocli.domain import installs
from hirocli.domain.config import Config, save_config
from hirocli.domain.hiro_home import ENV_HIRO_HOME, app_folder
from hirocli.domain.packages import PackageRefused, keep_package, stored_package
from hirocli.services import app_install, app_upgrade

KEY = "example.hello"


def manifest(version: str, **change) -> Manifest:
    fields = {"key": KEY, "kind": "app", "title": "Hello", "version": version, "core": ">=0.0",
              "command": "example-hello", "port": 8190, "predeploy": "python -m hello.predeploy"}
    return Manifest(**{**fields, **change})


def package(workspace: Path, m: Manifest) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(MANIFEST_FILE, render_manifest(m))
        zf.writestr("requirements.txt", "")
        zf.writestr(f"wheels/example_hello-{m.version}-py3-none-any.whl", "x")
    return keep_package(workspace, [buffer.getvalue()])


class Fake:
    """The faked system and app: the service's state, every predeploy step run (step, release, copy), health."""

    def __init__(self, monkeypatch, *, trial_fails: bool = False, healthy: bool = True) -> None:
        self.running = True
        self.events: list[str] = []
        self.steps: list[tuple[str, str, str]] = []
        self.healthy = healthy
        monkeypatch.setattr(app_system, "is_running", lambda service: self.running)
        monkeypatch.setattr(app_system, "start", self._start)
        monkeypatch.setattr(app_system, "stop", self._stop)

        def unpack(pkg, folder, workspace_path):
            release = folder.release(pkg.manifest.version)
            release.mkdir(parents=True, exist_ok=True)
            (release / MANIFEST_FILE).write_text(render_manifest(pkg.manifest), encoding="utf-8")
            return release

        def predeploy(release, m, folder, step, copy, allowed=None):
            self.steps.append((step, release.name, copy))
            if step == "trial" and trial_fails:
                raise app_upgrade.UpgradeFailed("Its trial step failed: the migration failed")
            return "migrations-seconds=2" if step == "trial" else ""

        monkeypatch.setattr(app_install, "unpack", unpack)
        monkeypatch.setattr(app_upgrade, "run_predeploy", predeploy)
        monkeypatch.setattr(app_upgrade, "answers", lambda port, health, version, within_s: self.healthy)

    def _start(self, service: str) -> None:
        self.running = True
        self.events.append("start")

    def _stop(self, service: str) -> None:
        self.running = False
        self.events.append("stop")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    """An install of Hello 0.1.0, running, its release with its manifest, current pointing at it."""
    ws = tmp_path / "ws"
    ws.mkdir()
    save_config(ws, Config(http_port=7491, admin_port=7492, extension_port=7493))
    monkeypatch.setenv(ENV_HIRO_HOME, str(tmp_path / "home"))
    installs.add_install(ws, key=KEY, kind="app", title="Hello", version="0.1.0", port=8190,
                         service="hiro-example-hello", account="hiro-example-hello", home=str(tmp_path / "home"),
                         command="example-hello")
    installs.code_used(ws, KEY)  # running
    folder = app_folder(KEY)
    release = folder.release("0.1.0")
    release.mkdir(parents=True)
    (release / MANIFEST_FILE).write_text(render_manifest(manifest("0.1.0")), encoding="utf-8")
    folder.data.mkdir(parents=True)
    app_install.point_current(folder, release)
    return ws


def _current(version: str) -> bool:
    folder = app_folder(KEY)
    return Path(os.path.realpath(folder.current)) == Path(os.path.realpath(folder.release(version)))


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def test_the_pure_rules() -> None:
    assert app_upgrade.newer("0.1.10", "0.1.9") and not app_upgrade.newer("0.1.0", "0.1.0")
    assert app_upgrade.stamp().startswith("pre-deploy-")
    assert app_upgrade.predeploy_module(manifest("0.1.1")) == "hello.predeploy"
    assert app_upgrade.predeploy_module(manifest("0.1.1", predeploy="")) is None
    with pytest.raises(app_upgrade.UpgradeFailed, match="runs nothing else"):
        app_upgrade.predeploy_module(manifest("0.1.1", predeploy="python -m x; rm -rf /"))
    assert app_upgrade.migrations_seconds("tried\nmigrations-seconds=12") == 12
    trace = "The new migrations are not safe on a copy:\n- the migration failed:\nTraceback ...\nRuntimeError: on purpose"
    assert app_upgrade.summary(trace) == "The new migrations are not safe on a copy: RuntimeError: on purpose"
    assert app_upgrade.releases_to_prune(["0.1.0", "0.1.10", "0.1.9", "0.1.2", "0.1.1"], {"0.1.10", "0.1.0"}) == \
        ["0.1.1"]


@pytest.mark.parametrize(
    ("change", "words"),
    [({"version": "0.1.0"}, "newer version"), ({"version": "0.0.9"}, "newer version"),
     ({"command": "other"}, "install it again"), ({"core": ">=99"}, "works with the core")],
)
def test_an_upgrade_that_cant_be_is_refused_before_anything_changes(workspace: Path, monkeypatch, change: dict,
                                                                    words: str) -> None:
    fake = Fake(monkeypatch)
    m = manifest(**{"version": "0.1.1", **change})
    with pytest.raises(PackageRefused, match=words):
        app_upgrade.upgrade(workspace, KEY, package(workspace, m))
    assert installs.get_install(workspace, KEY).state == installs.RUNNING and fake.events == [] and fake.steps == []


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------


def test_an_upgrade_tries_first_copies_again_at_the_stop_switches_and_settles(workspace: Path, monkeypatch) -> None:
    fake = Fake(monkeypatch)
    package_id = package(workspace, manifest("0.1.1"))
    done = app_upgrade.upgrade(workspace, KEY, package_id)
    assert (done.outcome, done.before, done.to) == ("upgraded", "0.1.0", "0.1.1")
    first, at_stop = fake.steps[0][2], fake.steps[2][2]
    assert [(s, r) for s, r, _ in fake.steps] == [("snapshot", "0.1.0"), ("trial", "0.1.1"), ("snapshot", "0.1.0"),
                                                  ("settled", "0.1.1")]
    assert fake.steps[1][2] == first and at_stop > first  # the trial on the first copy; a newer one at the stop
    assert fake.events == ["stop", "start"] and _current("0.1.1")
    row = installs.get_install(workspace, KEY)
    assert (row.state, row.version, row.previous_version, row.upgrade_to) == (installs.RUNNING, "0.1.1", "0.1.0", "")
    with pytest.raises(PackageRefused):
        stored_package(workspace, package_id)


def test_a_failed_trial_leaves_the_app_running_as_it_was(workspace: Path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING)
    fake = Fake(monkeypatch, trial_fails=True)
    done = app_upgrade.upgrade(workspace, KEY, package(workspace, manifest("0.1.1")))
    assert done.outcome == "stayed" and "stays on 0.1.0" in done.words
    assert fake.events == [] and _current("0.1.0")  # never stopped
    assert not app_folder(KEY).release("0.1.1").exists()
    row = installs.get_install(workspace, KEY)
    assert (row.state, row.version, row.upgrade_to) == (installs.RUNNING, "0.1.0", "")
    assert any(r.levelno == logging.WARNING and r.getMessage().startswith("⚠️ Upgrade refused — Hello stays on 0.1.0")
               for r in caplog.records)


def test_no_answer_puts_back_the_data_copied_at_the_stop_and_the_version_before(workspace: Path, monkeypatch) -> None:
    fake = Fake(monkeypatch, healthy=False)
    done = app_upgrade.upgrade(workspace, KEY, package(workspace, manifest("0.1.1")))
    assert done.outcome == "stayed" and "0.1.1 didn't answer" in done.words
    at_stop = fake.steps[2][2]
    assert fake.steps[-1] == ("restore", "0.1.0", at_stop)  # by the old release, from the copy at the stop
    assert fake.events == ["stop", "start", "stop", "start"] and _current("0.1.0")
    assert not app_folder(KEY).release("0.1.1").exists()
    assert installs.get_install(workspace, KEY).state == installs.RUNNING


def test_the_upgrade_is_its_own_story_titled_by_where_it_ended(workspace: Path, monkeypatch, caplog) -> None:
    from hiro_commons.logging_foundation.line import ATTRIBUTES

    from hirocli.tools import extension_install as tools

    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(tools, "_resolve_path", lambda workspace: workspace_path)
    workspace_path = workspace
    Fake(monkeypatch, healthy=False)
    result = tools.ExtensionUpgradeTool().execute(key=KEY, package=package(workspace, manifest("0.1.1")))
    assert result.outcome == "stayed"
    fields = [getattr(r, ATTRIBUTES, {}) or {} for r in caplog.records]
    assert any(f.get("story.name") == "core.extension_upgrade" for f in fields)
    titles = [f.get("story.title") for f in fields if f.get("story.title")]
    assert "Hello stays on 0.1.0: 0.1.1 didn't answer" in titles


# ---------------------------------------------------------------------------
# A restart in the middle
# ---------------------------------------------------------------------------


def _cut_off_at(workspace: Path, step: str, *, switched: bool) -> None:
    folder = app_folder(KEY)
    new = folder.release("0.1.1")
    new.mkdir(parents=True, exist_ok=True)
    (new / MANIFEST_FILE).write_text(render_manifest(manifest("0.1.1")), encoding="utf-8")
    installs.set_upgrade(workspace, KEY, step=step, to="0.1.1", stamp="pre-deploy-20261126T120000000000Z")
    if switched:
        app_install.point_current(folder, new)


def test_a_restart_before_the_switch_drops_the_new_release(workspace: Path, monkeypatch) -> None:
    fake = Fake(monkeypatch)
    _cut_off_at(workspace, app_upgrade.TRYING, switched=False)
    assert app_upgrade.resume(workspace) == [f"{KEY}: stays on 0.1.0"]
    assert fake.events == [] and fake.steps == [] and not app_folder(KEY).release("0.1.1").exists()
    assert installs.get_install(workspace, KEY).state == installs.RUNNING


@pytest.mark.parametrize(("step", "switched", "restored"), [
    (app_upgrade.SWITCHING, False, False),  # stopped, but the new release never ran: nothing to put back
    (app_upgrade.CHECKING, True, True),
    (app_upgrade.GOING_BACK, True, True),  # cut off while going back: done again
])
def test_a_restart_from_the_switch_on_goes_back_and_can_go_back_again(workspace: Path, monkeypatch, step: str,
                                                                       switched: bool, restored: bool) -> None:
    fake = Fake(monkeypatch)
    fake.running = False
    _cut_off_at(workspace, step, switched=switched)
    [line] = app_upgrade.resume(workspace)
    assert "stays on 0.1.0" in line and _current("0.1.0") and fake.running
    assert [s for s, *_ in fake.steps] == (["restore"] if restored else [])
    assert installs.get_install(workspace, KEY).state == installs.RUNNING
    assert app_upgrade.resume(workspace) == []  # nothing left to do


def test_going_back_that_fails_leaves_it_failed_with_words_and_no_loop(workspace: Path, monkeypatch) -> None:
    Fake(monkeypatch)
    _cut_off_at(workspace, app_upgrade.CHECKING, switched=True)

    def broken(service: str) -> None:
        raise app_system.ServiceError("the service won't start")

    monkeypatch.setattr(app_system, "start", broken)
    [line] = app_upgrade.resume(workspace)
    assert "couldn't go back" in line
    row = installs.get_install(workspace, KEY)
    assert row.state == installs.FAILED and "Remove it" in row.step
    assert app_upgrade.resume(workspace) == []


def test_while_it_upgrades_it_isnt_started_stopped_or_upgraded_again(workspace: Path, monkeypatch) -> None:
    from hirocli.tools import extension_install as tools

    monkeypatch.setattr(tools, "_resolve_path", lambda workspace: workspace_path)
    workspace_path = workspace
    Fake(monkeypatch)
    _cut_off_at(workspace, app_upgrade.TRYING, switched=False)
    assert tools.ExtensionStopTool().execute(key=KEY).refused == "upgrading"
    with pytest.raises(PackageRefused, match="upgrading already"):
        app_upgrade.upgrade(workspace, KEY, package(workspace, manifest("0.1.2")))


def test_only_what_the_new_version_newly_asks_waits(workspace: Path, monkeypatch) -> None:
    from hiro_channel_sdk.approvals import PEOPLE_NOTIFY, PEOPLE_SEE, AppAsk

    optional = AppAsk(permission=PEOPLE_NOTIFY, required=False)
    before = manifest("0.1.0", asks=(optional,))  # left off at install: asked before, so not "more"
    after = manifest("0.1.1", asks=(optional, AppAsk(permission=PEOPLE_SEE)))
    row = installs.get_install(workspace, KEY)
    assert app_upgrade.new_asks(workspace, row, after, before) == ["read the people list: names, WhatsApp numbers, roles"]
