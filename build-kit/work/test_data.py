"""data.py: env1..env5 read no real system and call no AI unless asked; a live copy is scrubbed before it leaves
Simone; env0 keeps its own settings when a live copy takes its place."""

import json
import sqlite3
import subprocess
import sys
from contextlib import closing

import data


def db(path, sql):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript(sql)
    return path


def rows(path, sql):
    with closing(sqlite3.connect(path)) as con:
        return con.execute(sql).fetchall()


SETTING = "create table setting(key text primary key, value text);"


def env_copy(tmp_path):
    d = tmp_path / "env3"
    db(d / "homehiro" / "homehiro.db", SETTING + "insert into setting values ('ha_url','http://homeassistant.local'),"
       "('ha_token','t'),('mqtt_host','192.168.1.10'),('mqtt_password','p'),('status_home_tz','Africa/Cairo');")
    db(d / "nethiro" / "nethiro.db", SETTING + "insert into setting values ('ha_url','x'),('adguard_login','{}'),"
       "('dns_blocking','{}'); create table statusitem(id integer, enabled boolean);"
       "insert into statusitem values (1, 1), (2, 1), (3, 0);")
    db(d / "trainhiro" / "trainhiro.db", SETTING + "insert into setting values ('frigate_url','http://f:5000');")
    (d / "core" / "default").mkdir(parents=True)
    (d / "core" / "default" / "providers.json").write_text(
        json.dumps({"version": 1, "providers": [{"provider_id": "google"}, {"provider_id": "codex"}]}),
        encoding="utf-8")
    return d


def test_by_default_an_environment_copy_reads_no_real_system_and_has_no_ai(tmp_path):
    d = env_copy(tmp_path)
    did = data.make_safe(d, [])
    assert rows(d / "homehiro" / "homehiro.db", "select key from setting") == [("status_home_tz",)]
    assert rows(d / "nethiro" / "nethiro.db", "select key from setting") == [("dns_blocking",)]
    assert rows(d / "nethiro" / "nethiro.db", "select count(*) from statusitem where enabled") == [(0,)]
    assert rows(d / "trainhiro" / "trainhiro.db", "select count(*) from setting") == [(0,)]
    assert json.loads((d / "core" / "default" / "providers.json").read_text())["providers"] == []
    assert any("AI provider" in line for line in did)
    assert data.make_safe(d, []) == []  # again: nothing left to do


def test_a_task_that_asks_keeps_the_real_reads_and_the_ai(tmp_path):
    d = env_copy(tmp_path)
    assert data.make_safe(d, [data.READS, data.AI]) == []
    assert len(rows(d / "homehiro" / "homehiro.db", "select key from setting")) == 5
    assert rows(d / "nethiro" / "nethiro.db", "select count(*) from statusitem where enabled") == [(2,)]
    assert len(json.loads((d / "core" / "default" / "providers.json").read_text())["providers"]) == 2


def test_app_settings_and_the_core_environment_follow_what_the_task_asked():
    assert data.env_overrides("homehiro", []) == {"TALKER_KEY": None, "AUTOMATION_BUDGET_USD": "0"}
    assert data.env_overrides("homehiro", [data.AI]) == {"TALKER_KEY": None}
    assert data.env_overrides("trainhiro", []) == {"FRIGATE_URL": None}
    assert data.env_overrides("trainhiro", [data.READS]) == {}
    environ = {"GEMINI_API_KEY": "x", "CLOUDFLARE_API_TOKEN": "y", "PATH": "p"}
    assert data.core_env(environ, []) == {"GEMINI_API_KEY": "", "CLOUDFLARE_API_TOKEN": ""}
    assert data.core_env(environ, [data.AI]) == {}


def test_an_environment_gets_env0s_pictures_as_hard_links_and_its_own_changes_stay_there(tmp_path):
    env0, env = tmp_path / "env0" / "studyhiro", tmp_path / "env1" / "studyhiro"
    (env0 / "files" / "sub").mkdir(parents=True)
    (env0 / "files" / "a.jpg").write_bytes(b"a")
    (env0 / "files" / "sub" / "b.jpg").write_bytes(b"b")
    (env0 / "streams").mkdir()  # not a picture folder: never linked
    (env0 / "streams" / "clip.mp4").write_bytes(b"c")
    assert data.link_pictures(env0, env, "studyhiro") == ["studyhiro/files: 2 file(s) linked"]
    assert (env / "files" / "a.jpg").samefile(env0 / "files" / "a.jpg")  # the same file, no copy
    assert (env / "files" / "sub" / "b.jpg").read_bytes() == b"b"
    assert not (env / "streams").exists()
    (env / "files" / "new.jpg").write_bytes(b"n")  # a task's new picture stays in its environment
    (env / "files" / "a.jpg").unlink()  # removing one there removes only its link
    assert not (env0 / "files" / "new.jpg").exists() and (env0 / "files" / "a.jpg").read_bytes() == b"a"
    assert data.link_pictures(env0, env, "nethiro") == []  # an app with no picture folders


def test_per_place_settings_are_addresses_logins_and_tokens():
    for key in ("ha_url", "ha_token", "mqtt_password", "adguard_login", "tv_key", "hiroleague_url", "nethiro_url",
                "core_ai_profiles", "some_new_secret"):
        assert data.is_place_key(key), key
    for key in ("status_home_tz", "dns_blocking", "points_rules", "home_devices", "traffic_settings"):
        assert not data.is_place_key(key), key


def live_home(tmp_path, monkeypatch):
    """A fake Simone: the live databases in tmp folders, as LIVE names them."""
    live = tmp_path / "live"
    db(live / "homehiro" / "homehiro.db", "pragma journal_mode=wal;" + SETTING +
       "insert into setting values ('ha_token','live-secret-token'),('ha_url','http://ha'),('status_home_tz','tz');"
       "create table websession(id text primary key, user_id text);"
       "insert into websession values ('live-session-cookie','p1');"
       "create table person(id integer, name text); insert into person values (1,'A'),(2,'B'),(3,'C');")
    db(live / "core" / "workspace.db", "create table people(person_id text, name text, password_hash text);"
       "insert into people values ('p1','A','h');"
       "create table extensions(extension_id text, public_key text); insert into extensions values ('e1','live-key');")
    monkeypatch.setattr(data, "LIVE", {"homehiro": (str(live / "homehiro"), ["homehiro.db"]),
                                       "core": (str(live / "core"), ["workspace.db", "data.db"])})
    return live


def test_a_live_copy_is_scrubbed_before_it_leaves_simone(tmp_path, monkeypatch):
    live_home(tmp_path, monkeypatch)
    out = tmp_path / "copy"
    run = subprocess.run([sys.executable, "-"], input=data.scrub_script(str(out)), capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    meta = json.loads(run.stdout)
    hh = meta["homehiro/homehiro.db"]
    assert hh["live"]["websession"] == 1 and hh["copy"]["websession"] == 0
    assert hh["scrubbed"]["setting"] == ["ha_token", "ha_url"]
    assert hh["copy"]["person"] == hh["live"]["person"] == 3 and hh["check"] == "ok"
    assert meta["core/data.db"] == {"missing": True}
    assert meta["core/workspace.db"]["scrubbed"] == {"extensions": 1}
    raw = (out / "homehiro" / "homehiro.db").read_bytes()
    assert b"live-secret-token" not in raw and b"live-session-cookie" not in raw  # overwritten, not only unlinked
    assert not (out / "homehiro" / "homehiro.db-wal").exists()
    assert rows(out / "homehiro" / "homehiro.db", "select key from setting") == [("status_home_tz",)]


def test_env0_keeps_its_own_settings_sessions_and_pairings_when_a_live_copy_takes_its_place(tmp_path):
    live = db(tmp_path / "copy" / "homehiro.db", SETTING + "insert into setting values ('status_home_tz','live-tz');"
              "create table websession(id text, user_id text, device text);"
              "create table person(id integer, name text); insert into person values (1,'A'),(2,'B');")
    old = db(tmp_path / "env0" / "homehiro.db", SETTING + "insert into setting values ('ha_url','http://dev'),"
             "('ha_token','dev-token'),('status_home_tz','old-tz');"
             "create table websession(id text, user_id text); insert into websession values ('s','u');"
             "create table person(id integer, name text); insert into person values (9,'old');")
    new = tmp_path / "env0" / "homehiro.db.refresh"
    counts, back = data.build(live, old, new, "homehiro.db")
    assert dict(rows(new, "select key, value from setting")) == {
        "status_home_tz": "live-tz", "ha_url": "http://dev", "ha_token": "dev-token"}
    assert rows(new, "select id, user_id, device from websession") == [("s", "u", None)]
    assert rows(new, "select name from person order by id") == [("A",), ("B",)]
    assert counts == {"person": 2, "setting": 3, "websession": 1} and back == {"setting": 2, "websession": 1}


def test_a_new_database_with_no_env0_copy_is_taken_as_it_is(tmp_path):
    live = db(tmp_path / "copy" / "streams.db", "create table streamrecord(id integer); insert into streamrecord values (1);")
    counts, back = data.build(live, tmp_path / "env0" / "streams.db", tmp_path / "streams.db.refresh", "streams.db")
    assert counts == {"streamrecord": 1} and back == {}


def test_the_report_shows_live_copy_and_env0_with_what_was_left_out():
    meta = {"homehiro/homehiro.db": {"live": {"setting": 5, "websession": 2, "person": 3},
                                     "copy": {"setting": 3, "websession": 0, "person": 3},
                                     "scrubbed": {"setting": ["ha_token", "ha_url"], "websession": 2},
                                     "check": "ok", "alembic": "abc", "bytes": 2**20},
            "core/data.db": {"missing": True}}
    text = data.report(meta, {}, {"homehiro/homehiro.db": {"setting": 4, "websession": 1, "person": 3}},
                       {"homehiro/homehiro.db": {"setting": 1, "websession": 1}})
    assert "not copied: ha_token, ha_url; env0's 1 kept" in text
    assert "2 row(s) not copied; env0's 1 kept" in text
    assert "core/data.db: not on Simone" in text
