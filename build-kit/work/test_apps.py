"""apps.toml: the apps hiro-work knows, their ports in an environment's 50-port block."""

import pytest

import apps


def test_every_app_has_two_ports_and_no_two_share_one():
    p = apps.ports(3)
    assert len(set(p.values())) == len(p) == 7 + 2 * len(apps.APPS)
    assert (p["core-admin"], p["core-socket"], p["core-ui"], p["core-http"], p["core-plugin"], p["core-gateway"]) == (
        7300, 7301, 7302, 7313, 7314, 7317)
    assert all(7300 <= port < 7350 for port in p.values())


def test_the_ports_stay_where_they_were():
    p = apps.ports(0)
    assert [p[f"{r}-{s}"] for r in ("homehiro", "nethiro", "trainhiro", "studyhiro", "codehiro")
            for s in ("api", "ui")] == list(range(7003, 7013))


def test_a_port_belongs_to_its_environment_up_to_7N49():
    assert apps.env_of_port(7049) == 0 and apps.env_of_port(7215) == 2
    assert apps.env_of_port(7050) is None and apps.env_of_port(6999) is None and apps.env_of_port(7600) is None


ROW = """[[app]]
repo = "newhiro"
name = "new"
title = "NewHiro"
api_port = {api}
ui_port = 16
backend = "backend"
api = "uv run uvicorn newhiro.main:app --port {{port}}"
frontend = "frontend"
ui_api_env = "NEWHIRO_API"
data = "{data}"
settings_db = "newhiro.db"
site_key = "newhiro_url"
live_port = 8150
copy_data = true
"""


def test_a_new_row_takes_the_next_free_ports(tmp_path):
    f = tmp_path / "apps.toml"
    f.write_text(ROW.format(api=15, data="env"), encoding="utf-8")
    [a] = apps.load(f)
    assert apps.ports(1, [a])["newhiro-ui"] == 7116


@pytest.mark.parametrize("api, data, words", [(13, "env", "core-http's"), (50, "env", "outside"),
                                                (15, "nowhere", "'env' or 'repo'")])
def test_a_wrong_row_is_refused(tmp_path, api, data, words):
    f = tmp_path / "apps.toml"
    f.write_text(ROW.format(api=api, data=data), encoding="utf-8")
    with pytest.raises(ValueError, match=words):
        apps.load(f)
