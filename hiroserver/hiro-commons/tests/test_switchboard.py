"""The switchboard: live reaches everything; a test environment only what its file says; a broken file opens nothing."""

import json

import pytest

from hiro_commons import switchboard as sb


def board(tmp_path, modes, **more):
    path = tmp_path / "switchboard.json"
    path.write_text(json.dumps({"place": "env2", "preset": "safe", "modes": modes, **more}), encoding="utf-8")
    return sb.read({sb.ENV: str(path)})


def test_with_no_file_named_everything_is_real_as_live():
    live = sb.read({})
    assert live.live and live.mode("ha") == "real" and live.check("ai", write=True) == "real"
    assert live.summary() is None


def test_read_only_reads_and_refuses_every_write_saying_where(tmp_path):
    b = board(tmp_path, {"ha": "read"})
    assert b.check("ha") == "read"
    with pytest.raises(sb.Refused, match="Home Assistant is read only in env2"):
        b.check("ha", write=True)


def test_off_and_a_system_the_file_doesnt_name_are_refused(tmp_path):
    b = board(tmp_path, {"ai": "off"})
    with pytest.raises(sb.Refused, match="AI is off in env2"):
        b.check("ai")
    with pytest.raises(sb.Refused, match="Frigate is off"):
        b.check("frigate")


def test_fake_goes_on_only_where_the_caller_has_a_stand_in(tmp_path):
    b = board(tmp_path, {"whatsapp": "fake"})
    assert b.check("whatsapp", write=True, fakes=True) == "fake"
    with pytest.raises(sb.Refused, match="no stand-in yet"):
        b.check("whatsapp", write=True)


def test_a_mode_a_system_cant_take_is_off(tmp_path):
    b = board(tmp_path, {"mqtt": "real", "dhcp": "read"})  # MQTT only listens; DHCP has nothing to only read
    assert (b.mode("mqtt"), b.mode("dhcp")) == ("off", "off")


def test_a_file_that_cant_be_read_opens_nothing(tmp_path):
    for env in ({sb.ENV: str(tmp_path / "missing.json")},):
        b = sb.read(env)
        assert not b.live and b.problem and all(b.mode(s) == "off" for s in sb.SYSTEMS)
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert sb.read({sb.ENV: str(tmp_path / "bad.json")}).mode("ha") == "off"


def test_the_summary_says_every_systems_mode(tmp_path):
    s = board(tmp_path, {"ha": "read", "ai": "real"}).summary()
    assert (s["place"], s["preset"], s["modes"]["ha"], s["modes"]["ai"], s["modes"]["dhcp"]) == ("env2", "safe", "read", "real", "off")


def test_a_page_gets_the_systems_its_app_reaches_and_live_gets_none(tmp_path):
    p = board(tmp_path, {"ha": "read", "ai": "fake", "tv": "read"}).page(["tv", "ai", "ha"])
    assert (p["place"], p["preset"]) == ("env2", "safe")
    assert p["systems"] == [{"id": "ha", "name": "Home Assistant", "mode": "read"},
                            {"id": "ai", "name": "AI", "mode": "fake"}, {"id": "tv", "name": "TVs", "mode": "read"}]
    assert sb.read({}).page(["ha"]) is None
