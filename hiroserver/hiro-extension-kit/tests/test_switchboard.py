"""The kit's gate: an app's own outside systems follow the place's switchboard; live refuses nothing."""

import json

import pytest
from hiro_commons import switchboard as commons

from hiro_extension_kit import errors, switchboard


@pytest.fixture
def board(tmp_path, monkeypatch):
    def use(modes):
        path = tmp_path / "switchboard.json"
        path.write_text(json.dumps({"place": "env3", "preset": "Safe", "modes": modes}), encoding="utf-8")
        monkeypatch.setattr(commons, "_board", commons.read({commons.ENV: str(path)}))

    yield use
    monkeypatch.setattr(commons, "_board", None)


def test_live_gates_nothing(monkeypatch):
    monkeypatch.setattr(commons, "_board", commons.read({}))
    assert switchboard.gate("ha", write=True) == "real"
    assert switchboard.reaches("frigate") and switchboard.writes("adguard") and switchboard.summary() is None


def test_read_only_reads_and_refuses_a_write_as_unavailable(board):
    board({"ha": "read"})
    assert switchboard.gate("ha") == "read" and switchboard.reaches("ha") and not switchboard.writes("ha")
    with pytest.raises(errors.Unavailable, match="Home Assistant is read only in env3"):
        switchboard.gate("ha", write=True)


def test_off_isnt_reached_and_fake_only_by_a_caller_with_a_stand_in(board):
    board({"frigate": "off", "talker": "fake"})
    assert not switchboard.reaches("frigate")
    with pytest.raises(errors.Unavailable, match="Frigate is off in env3"):
        switchboard.gate("frigate")
    assert switchboard.gate("talker", write=True, fakes=True) == "fake"
    with pytest.raises(errors.Unavailable):
        switchboard.gate("talker", write=True)
    assert switchboard.summary()["modes"]["talker"] == "fake"


def test_a_page_gets_the_modes_of_the_systems_the_app_declares(board):
    board({"ha": "read", "ai": "fake", "frigate": "read"})
    here = switchboard.page()
    assert (here["place"], here["preset"]) == ("env3", "Safe")
    assert [(s["id"], s["mode"]) for s in here["systems"]] == [("ha", "read"), ("ai", "fake")]  # the test app's two


def test_who_is_asking_says_the_place_and_live_says_none(board, monkeypatch):
    from hiro_extension_kit.auth.api import MeOut

    def me():
        return MeOut(id="p", name="P", way="dev", state="ok", role_id=None, role_name=None, owner=True, access={})

    board({"ha": "read"})
    assert me().place.place == "env3" and me().place.systems[0].name == "Home Assistant"
    monkeypatch.setattr(commons, "_board", commons.read({}))
    assert me().place is None
