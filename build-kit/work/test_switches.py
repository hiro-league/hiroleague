"""switches.py: presets, an environment's switchboard file, and what the copy lists hear of it."""

import pytest

import switches as sw


@pytest.fixture
def presets(tmp_path):
    path = tmp_path / "presets.toml"
    path.write_text(sw.PRESETS.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_the_built_in_presets_name_every_system_with_a_mode_it_can_take():
    assert [p["name"] for p in sw.presets() if p["builtin"]] == ["Safe", "AI", "Offline", "Full real"]
    for p in sw.presets():
        assert set(p["modes"]) == set(sw.SYSTEMS)


def test_safe_reads_the_house_and_nothing_real_is_written_or_paid():
    safe = sw.resolve("safe")  # any case
    assert "real" not in safe.values()
    assert sw.real_of(safe) == ["reads"]
    assert sw.real_of(sw.resolve("Offline")) == []
    assert sw.real_of(sw.resolve("Safe", {"ai": "real"})) == ["reads", "ai"]
    assert sw.real_of(sw.resolve("Safe", {"adguard": "real"})) == ["reads", "writes"]


@pytest.mark.parametrize("sets, says", [
    (["ai"], "write it as"),
    (["wifi=real"], "no system wifi"),
    (["mqtt=real"], "MQTT can't be 'real'"),
])
def test_a_wrong_change_is_refused_saying_why(sets, says):
    with pytest.raises(sw.SwitchError, match=says):
        sw.parse_sets(sets)


def test_an_environments_file_holds_its_preset_changes_and_every_mode(tmp_path):
    rec = sw.write(tmp_path, 2, "ai", {"ha": "real"})
    assert sw.read(tmp_path) == rec
    assert (rec["place"], rec["preset"], rec["changes"]) == ("env2", "AI", {"ha": "real"})
    assert rec["modes"]["ha"] == "real" and rec["modes"]["whatsapp"] == "fake"
    assert sw.describe(rec) == "switchboard: AI +1 | real: Home Assistant, AI, Voices"
    assert sw.board.read({sw.ENV: str(tmp_path / sw.FILE)}).mode("ha") == "real"  # as the servers read it


def test_a_combination_is_saved_as_a_preset_used_and_removed(presets):
    modes = sw.resolve("Safe", {"ha": "real"}, presets)
    sw.save_preset("HA real", modes, "for device tests", presets)
    assert sw.preset("ha real", presets)["modes"]["ha"] == "real" and not sw.preset("HA real", presets)["builtin"]
    with pytest.raises(sw.SwitchError, match="already"):
        sw.save_preset("ha REAL", modes, path=presets)
    with pytest.raises(sw.SwitchError, match="name is"):
        sw.save_preset('bad"name', modes, path=presets)
    sw.remove_preset("HA real", presets)
    assert [p["name"] for p in sw.presets(presets)] == ["Safe", "AI", "Offline", "Full real"]
    with pytest.raises(sw.SwitchError, match="built in"):
        sw.remove_preset("Safe", presets)
