"""data.py and copylist.py: each repo's copy list says what a copy holds; env1..env5 read the real systems but write to
none and call no AI unless asked; a live copy is scrubbed before it leaves Simone; env0 keeps its own settings when a
live copy takes its place."""

import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

import copylist
import data

HERE = Path(__file__).resolve().parent


def db(path, sql):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript(sql)
    return path


def rows(path, sql):
    with closing(sqlite3.connect(path)) as con:
        return con.execute(sql).fetchall()


SETTING = "create table setting(key text primary key, value text);"

# Small lists in the real ones' shape: the core's, HomeHiro's, NetHiro's, TrainHiro's, StudyHiro's
CORE_LIST = '''
live = "LIVE/core"
[every_app]
place_key_pattern = "token|password|secret|login|_key$|_url$"
place_keys = ["hiroleague_url", "core_ai_profiles"]
[[item]]
path = "db/workspace.db"
kind = "database"
live = "copy"
envs = "copy"
place_tables = ["extensions", "channel_plugins"]
why = "the family"
[[item]]
path = "db/data.db"
kind = "database"
live = "copy"
envs = "copy"
why = "chats"
[[item]]
path = "db/graphiti_kuzu.db"
kind = "file"
live = "own"
envs = "copy"
optional = true
why = "the graph, locked while a core runs"
[[item]]
path = "providers.json"
kind = "file"
live = "own"
envs = "copy"
why = "providers"
[[item]]
path = "characters"
kind = "folder"
live = "own"
envs = "copy"
why = "characters"
[[item]]
path = "channels"
kind = "folder"
live = "own"
envs = "none"
why = "the WhatsApp session"
[[switch]]
path = "providers.json"
key = "providers"
value = []
unless = "ai"
why = "no AI call"
[[switch]]
path = "db/workspace.db"
table = "channel_plugins"
column = "enabled"
value = 0
why = "WhatsApp off"
[[env]]
match = "(API_KEY|API_TOKEN)$"
value = ""
unless = "ai"
why = "provider keys"
'''

APP_LISTS = {
    "homehiro": '''
live = "LIVE/homehiro"
[[item]]
path = "homehiro.db"
kind = "database"
live = "copy"
envs = "copy"
place_tables = ["websession"]
why = "everything"
[[item]]
path = "people"
kind = "folder"
live = "copy"
envs = "link"
why = "avatars"
[[item]]
path = "hiroleague"
kind = "folder"
live = "own"
envs = "copy"
why = "its key"
[[item]]
path = "streams"
kind = "folder"
live = "own"
envs = "none"
why = "camera history"
[[item]]
path = "*.before-*"
kind = "file"
live = "own"
envs = "none"
why = "snapshots"
[[setting]]
key = "ha_token"
needs = "reads"
why = "HA"
[[setting]]
key = "mqtt_host"
needs = "reads"
why = "MQTT"
[[setting]]
key = "tv_cast"
why = "the place's TV"
[[env]]
name = "TALKER_KEY"
drop = true
why = "Talker"
[[env]]
name = "AUTOMATION_BUDGET_USD"
value = "0"
unless = "ai"
why = "nothing to spend"
''',
    "nethiro": '''
live = "LIVE/nethiro"
[[item]]
path = "nethiro.db"
kind = "database"
live = "copy"
envs = "copy"
why = "health"
[[setting]]
key = "ha_url"
needs = "reads"
why = "HA"
[[setting]]
key = "adguard_login"
needs = "writes"
why = "AdGuard"
[[switch]]
path = "nethiro.db"
table = "statusitem"
column = "enabled"
value = 0
unless = "reads"
why = "health checks"
''',
    "trainhiro": '''
live = "LIVE/trainhiro"
[[item]]
path = "trainhiro.db"
kind = "database"
live = "copy"
envs = "copy"
why = "recognition"
[[setting]]
key = "frigate_url"
needs = "writes"
why = "Frigate"
[[env]]
name = "FRIGATE_URL"
drop = true
unless = "writes"
why = "Frigate"
''',
    "studyhiro": '''
live = "LIVE/studyhiro"
[[item]]
path = "studyhiro.db"
kind = "database"
live = "copy"
envs = "copy"
why = "studies"
[[item]]
path = "files"
kind = "folder"
live = "copy"
envs = "link"
why = "stored files"
''',
}


@pytest.fixture
def lists(tmp_path, monkeypatch):
    """The fixture lists, as hiro-work reads them from an environment's repos."""
    root = tmp_path / "repos"
    (root / "hiroleague").mkdir(parents=True)
    (root / "hiroleague" / "data.toml").write_text(CORE_LIST.replace("LIVE", (tmp_path / "live").as_posix()), "utf-8")
    for app, text in APP_LISTS.items():
        (root / app).mkdir()
        (root / app / "data.toml").write_text(text.replace("LIVE", (tmp_path / "live").as_posix()), "utf-8")
    monkeypatch.setattr(data, "APPS", list(APP_LISTS))
    return data.load(root)


# ----------------------------------------------------------------------------------------- the lists themselves


def test_the_cores_own_copy_list_reads_and_says_why_for_every_item():
    lst = copylist.parse((HERE.parent.parent / "data.toml").read_text("utf-8"), copylist.CORE)
    assert lst.every_app and "_url$" in lst.every_app.place_key_pattern
    assert {"db/workspace.db", "db/data.db", "db/knowledge.db"} == {i.path for i in lst.databases("live")}
    assert all(i.why for i in lst.items)
    assert lst.item("channels").envs == "none" and lst.item("plans").envs == "none"


@pytest.mark.parametrize("bad, says", [
    ('[[item]]\npath = "a.db"\nkind = "database"\nlive = "copy"\nenvs = "copy"\n', "missing why"),
    ('[[item]]\npath = "a.db"\nkind = "database"\nlive = "fetch"\nenvs = "copy"\nwhy = "w"\n', "live"),
    ('[[item]]\npath = "a.db"\nkind = "db"\nlive = "copy"\nenvs = "copy"\nwhy = "w"\n', "kind"),
    ('[[item]]\npath = "*.db"\nkind = "database"\nlive = "own"\nenvs = "none"\nwhy = "w"\n', "not a pattern"),
    ('[[item]]\npath = "a.json"\nkind = "file"\nlive = "own"\nenvs = "link"\nwhy = "w"\n', "only a folder"),
    ('[[item]]\npath = "a.db"\nkind = "database"\nlive = "copy"\nenvs = "copy"\nwhy = "w"\ncolour = "red"\n',
     "unknown field colour"),
    ('[[item]]\npath = "a"\nkind = "folder"\nlive = "own"\nenvs = "none"\nwhy = "w"\n'
     '[[switch]]\npath = "b.db"\ntable = "t"\ncolumn = "c"\nvalue = 0\nwhy = "w"\n', "no database or file item"),
    ('[[item]]\npath = "a"\nkind = "folder"\nlive = "own"\nenvs = "none"\nwhy = "w"\n'
     '[[env]]\nname = "X"\nwhy = "w"\n', "value or drop"),
    ('[[item]]\npath = "a"\nkind = "folder"\nlive = "own"\nenvs = "none"\nwhy = "w"\n'
     '[[setting]]\nkey = "k"\nneeds = "ai"\nwhy = "w"\n', "needs"),
    ('[[item]]\npath = "a"\nkind = "folder"\nlive = "own"\nenvs = "none"\nwhy = "w"\n'
     '[[item]]\npath = "a"\nkind = "folder"\nlive = "own"\nenvs = "none"\nwhy = "again"\n', "listed twice"),
    ('[[item]]\npath = "a"\nkind = "folder"\nlive = "own"\nenvs = "none"\nwhy = "w"\n'
     '[[setting]]\nkey = "k"\nwhy = "w"\n[[setting]]\nkey = "k"\nwhy = "again"\n', "listed twice"),
    ('[[item]]\npath = "a"\nkind = "folder"\nlive = "own"\nenvs = "none"\nwhy = "w"\n'
     '[[env]]\nname = "X"\ndrop = true\nwhy = "w"\n[[env]]\nname = "X"\nvalue = "1"\nwhy = "again"\n', "listed twice"),
])
def test_a_wrong_copy_list_stops_with_the_file_and_the_reason(bad, says):
    with pytest.raises(copylist.ListError, match=says):
        copylist.parse('live = "~/x/data"\n' + bad, "homehiro", "homehiro/data.toml")


def test_an_app_without_a_copy_list_is_named(tmp_path):
    (tmp_path / "hiroleague").mkdir()
    (tmp_path / "hiroleague" / "data.toml").write_text(CORE_LIST, "utf-8")
    with pytest.raises(copylist.ListError, match="evalhiro has no copy list"):
        copylist.load_all(tmp_path, ["evalhiro"])


def test_what_a_folder_holds_that_its_list_doesnt_name_is_found(lists):
    names = ["homehiro.db", "homehiro.db-wal", "people", "streams", "streams.db.before-rebuild", "tts-cache"]
    assert copylist.unlisted(lists["homehiro"], names) == ["tts-cache"]


# ----------------------------------------------------------------------------------------- env1..env5: safe


def env_copy(tmp_path):
    d = tmp_path / "env3"
    db(d / "homehiro" / "homehiro.db", SETTING + "insert into setting values ('ha_url','http://homeassistant.local'),"
       "('ha_token','t'),('mqtt_host','192.168.1.10'),('tv_cast','[]'),('status_home_tz','Africa/Cairo');")
    db(d / "nethiro" / "nethiro.db", SETTING + "insert into setting values ('ha_url','x'),('adguard_login','{}'),"
       "('dns_blocking','{}'); create table statusitem(id integer, enabled boolean);"
       "insert into statusitem values (1, 1), (2, 1), (3, 0);")
    db(d / "trainhiro" / "trainhiro.db", SETTING + "insert into setting values ('frigate_url','http://f:5000');")
    db(d / "core" / "default" / "db" / "workspace.db",
       "create table channel_plugins(name text, enabled boolean); insert into channel_plugins values ('whatsapp', 1);")
    (d / "core" / "default" / "providers.json").write_text(
        json.dumps({"version": 1, "providers": [{"provider_id": "google"}, {"provider_id": "codex"}]}),
        encoding="utf-8")
    return d


def test_by_default_an_environment_copy_reads_the_real_systems_but_keeps_no_login_that_writes_and_no_ai(
        tmp_path, lists):
    d = env_copy(tmp_path)
    did = data.make_safe(d, [data.READS], lists)
    assert len(rows(d / "homehiro" / "homehiro.db", "select key from setting")) == 5  # HA and MQTT kept
    assert rows(d / "nethiro" / "nethiro.db", "select key from setting order by key") == [("dns_blocking",), ("ha_url",)]
    assert rows(d / "nethiro" / "nethiro.db", "select count(*) from statusitem where enabled") == [(2,)]
    assert rows(d / "trainhiro" / "trainhiro.db", "select count(*) from setting") == [(0,)]  # Frigate writes
    assert json.loads((d / "core" / "default" / "providers.json").read_text())["providers"] == []
    assert rows(d / "core" / "default" / "db" / "workspace.db", "select enabled from channel_plugins") == [(0,)]
    assert "core: providers.json's 2 providers left out (no AI call)" in did


def test_a_task_that_reads_nothing_has_no_address_of_a_real_system(tmp_path, lists):
    d = env_copy(tmp_path)
    did = data.make_safe(d, [], lists)
    assert rows(d / "homehiro" / "homehiro.db", "select key from setting order by key") == [
        ("ha_url",), ("status_home_tz",), ("tv_cast",)]  # ha_url isn't in this small list
    assert rows(d / "nethiro" / "nethiro.db", "select key from setting") == [("dns_blocking",)]
    assert rows(d / "nethiro" / "nethiro.db", "select count(*) from statusitem where enabled") == [(0,)]
    assert "nethiro: 2 statusitem row(s) off (health checks)" in did
    assert data.make_safe(d, [], lists) == []  # again: nothing left to do


def test_a_task_that_asks_keeps_the_writes_and_the_ai_but_never_whatsapp(tmp_path, lists):
    d = env_copy(tmp_path)
    assert data.make_safe(d, [data.READS, data.WRITES, data.AI], lists) == [
        "core: 1 channel_plugins row(s) off (WhatsApp off)"]
    assert len(rows(d / "homehiro" / "homehiro.db", "select key from setting")) == 5
    assert rows(d / "trainhiro" / "trainhiro.db", "select count(*) from setting") == [(1,)]
    assert rows(d / "nethiro" / "nethiro.db", "select count(*) from statusitem where enabled") == [(2,)]
    assert len(json.loads((d / "core" / "default" / "providers.json").read_text())["providers"]) == 2


def test_app_settings_and_the_core_environment_follow_what_the_task_asked(lists):
    assert data.env_overrides("homehiro", [], lists) == {"TALKER_KEY": None, "AUTOMATION_BUDGET_USD": "0"}
    assert data.env_overrides("homehiro", [data.AI], lists) == {"TALKER_KEY": None}
    assert data.env_overrides("trainhiro", [], lists) == {"FRIGATE_URL": None}
    assert data.env_overrides("trainhiro", [data.READS], lists) == {"FRIGATE_URL": None}  # it writes to Frigate
    assert data.env_overrides("trainhiro", [data.WRITES], lists) == {}
    assert data.env_overrides("studyhiro", [], lists) == {}
    environ = {"GEMINI_API_KEY": "x", "CLOUDFLARE_API_TOKEN": "y", "PATH": "p"}
    assert data.core_env(environ, [], lists) == {"GEMINI_API_KEY": "", "CLOUDFLARE_API_TOKEN": ""}
    assert data.core_env(environ, [data.AI], lists) == {}


def test_an_environment_gets_env0s_pictures_as_hard_links_and_its_own_changes_stay_there(tmp_path, lists):
    env0, env = tmp_path / "env0" / "studyhiro", tmp_path / "env1" / "studyhiro"
    (env0 / "files" / "sub").mkdir(parents=True)
    (env0 / "files" / "a.jpg").write_bytes(b"a")
    (env0 / "files" / "sub" / "b.jpg").write_bytes(b"b")
    (env0 / "streams").mkdir()  # not a picture folder: never linked
    (env0 / "streams" / "clip.mp4").write_bytes(b"c")
    assert data.link_pictures(env0, env, "studyhiro", lists) == ["studyhiro/files: 2 file(s) linked"]
    assert (env / "files" / "a.jpg").samefile(env0 / "files" / "a.jpg")  # the same file, no copy
    assert (env / "files" / "sub" / "b.jpg").read_bytes() == b"b"
    assert not (env / "streams").exists()
    (env / "files" / "new.jpg").write_bytes(b"n")  # a task's new picture stays in its environment
    (env / "files" / "a.jpg").unlink()  # removing one there removes only its link
    assert not (env0 / "files" / "new.jpg").exists() and (env0 / "files" / "a.jpg").read_bytes() == b"a"
    assert data.link_pictures(env0, env, "nethiro", lists) == []  # an app with no picture folders


def test_an_environments_copy_takes_what_the_list_copies_and_names_what_it_doesnt_know(tmp_path, lists):
    src, dst = tmp_path / "env0" / "homehiro", tmp_path / "env2" / "homehiro"
    db(src / "homehiro.db", "pragma journal_mode=wal;" + SETTING + "insert into setting values ('a','1');")
    (src / "hiroleague").mkdir()
    (src / "hiroleague" / "extension_key.pem").write_text("k")
    (src / "people").mkdir()
    (src / "people" / "p.jpg").write_bytes(b"p")
    (src / "streams").mkdir()
    (src / "streams" / "big.mp4").write_bytes(b"s")
    (src / "tts-cache").mkdir()
    dst.mkdir(parents=True)
    lines = data.copy_group(src, dst, "homehiro", lists)
    assert rows(dst / "homehiro.db", "select value from setting") == [("1",)]  # with what was still in the WAL
    assert (dst / "hiroleague" / "extension_key.pem").read_text() == "k"
    assert (dst / "people" / "p.jpg").samefile(src / "people" / "p.jpg")
    assert not (dst / "streams").exists() and not (dst / "tts-cache").exists()
    assert lines == ["homehiro/people: 1 file(s) linked",
                     "! homehiro: not in its copy list, so not copied: tts-cache"]


def test_the_cores_copy_skips_an_optional_file_it_cant_read_and_never_takes_the_whatsapp_session(
        tmp_path, lists, monkeypatch):
    src, dst = tmp_path / "env0" / "core", tmp_path / "env2" / "core"
    db(src / "db" / "workspace.db", "create table people(id text);")
    (src / "db" / "graphiti_kuzu.db").write_bytes(b"graph")
    (src / "providers.json").write_text("{}")
    (src / "characters" / "hiro").mkdir(parents=True)
    (src / "channels").mkdir()
    (src / "channels" / "session.db").write_bytes(b"wa")
    dst.mkdir(parents=True)
    real_copy = data.shutil.copy2

    def locked(s, d, *a, **k):  # Kuzu's file, locked while env0's core runs
        if Path(s).name == "graphiti_kuzu.db":
            raise PermissionError(13, "locked")
        return real_copy(s, d, *a, **k)

    monkeypatch.setattr(data.shutil, "copy2", locked)
    lines = data.copy_group(src, dst, data.CORE, lists)
    assert (dst / "db" / "workspace.db").exists() and (dst / "providers.json").exists()
    assert (dst / "characters" / "hiro").is_dir() and not (dst / "channels").exists()
    assert lines == ["core/db/graphiti_kuzu.db: not copied (locked); the graph, locked while a core runs"]


# ----------------------------------------------------------------------------------------- live -> env0


def test_per_place_settings_are_the_kits_the_apps_own_and_addresses_logins_and_tokens(lists):
    for key in ("ha_url", "ha_token", "mqtt_host", "adguard_login", "tv_cast", "hiroleague_url", "nethiro_url",
                "core_ai_profiles", "some_new_secret"):
        assert data.is_place_key(key, "homehiro", lists), key
    for key in ("status_home_tz", "dns_blocking", "points_rules", "home_devices", "traffic_settings"):
        assert not data.is_place_key(key, "homehiro", lists), key
    assert not data.is_place_key("mqtt_host", "studyhiro", lists)  # HomeHiro's own key, not StudyHiro's


def live_home(tmp_path):
    """A fake Simone: the live databases in tmp folders, where the fixture lists name them."""
    live = tmp_path / "live"
    db(live / "homehiro" / "homehiro.db", "pragma journal_mode=wal;" + SETTING +
       "insert into setting values ('ha_token','live-secret-token'),('ha_url','http://ha'),('tv_cast','[1]'),"
       "('status_home_tz','tz');"
       "create table websession(id text primary key, user_id text);"
       "insert into websession values ('live-session-cookie','p1');"
       "create table person(id integer, name text); insert into person values (1,'A'),(2,'B'),(3,'C');")
    db(live / "core" / "db" / "workspace.db", "create table people(person_id text, name text, password_hash text);"
       "insert into people values ('p1','A','h');"
       "create table extensions(extension_id text, public_key text); insert into extensions values ('e1','live-key');")
    return live


def test_a_live_copy_is_scrubbed_before_it_leaves_simone(tmp_path, lists):
    live_home(tmp_path)
    out = tmp_path / "copy"
    run = subprocess.run([sys.executable, "-"], input=data.scrub_script(str(out), lists), capture_output=True,
                         text=True)
    assert run.returncode == 0, run.stderr
    meta = json.loads(run.stdout)
    hh = meta["homehiro/homehiro.db"]
    assert hh["live"]["websession"] == 1 and hh["copy"]["websession"] == 0
    assert hh["scrubbed"]["setting"] == ["ha_token", "ha_url", "tv_cast"]
    assert hh["copy"]["person"] == hh["live"]["person"] == 3 and hh["check"] == "ok"
    assert meta["core/db/data.db"] == {"missing": True}
    assert meta["core/db/workspace.db"]["scrubbed"] == {"extensions": 1}
    assert meta["nethiro/nethiro.db"] == {"missing": True}
    raw = (out / "homehiro" / "homehiro.db").read_bytes()
    assert b"live-secret-token" not in raw and b"live-session-cookie" not in raw  # overwritten, not only unlinked
    assert not (out / "homehiro" / "homehiro.db-wal").exists()
    assert rows(out / "homehiro" / "homehiro.db", "select key from setting") == [("status_home_tz",)]


def test_env0_keeps_its_own_settings_sessions_and_pairings_when_a_live_copy_takes_its_place(tmp_path, lists):
    live = db(tmp_path / "copy" / "homehiro.db", SETTING + "insert into setting values ('status_home_tz','live-tz');"
              "create table websession(id text, user_id text, device text);"
              "create table person(id integer, name text); insert into person values (1,'A'),(2,'B');")
    old = db(tmp_path / "env0" / "homehiro.db", SETTING + "insert into setting values ('ha_url','http://dev'),"
             "('ha_token','dev-token'),('status_home_tz','old-tz');"
             "create table websession(id text, user_id text); insert into websession values ('s','u');"
             "create table person(id integer, name text); insert into person values (9,'old');")
    new = tmp_path / "env0" / "homehiro.db.refresh"
    counts, back = data.build(live, old, new, "homehiro/homehiro.db", lists)
    assert dict(rows(new, "select key, value from setting")) == {
        "status_home_tz": "live-tz", "ha_url": "http://dev", "ha_token": "dev-token"}
    assert rows(new, "select id, user_id, device from websession") == [("s", "u", None)]
    assert rows(new, "select name from person order by id") == [("A",), ("B",)]
    assert counts == {"person": 2, "setting": 3, "websession": 1} and back == {"setting": 2, "websession": 1}


def test_a_new_database_with_no_env0_copy_is_taken_as_it_is(tmp_path, lists):
    live = db(tmp_path / "copy" / "data.db", "create table messages(id integer); insert into messages values (1);")
    counts, back = data.build(live, tmp_path / "env0" / "data.db", tmp_path / "data.db.refresh", "core/db/data.db",
                              lists)
    assert counts == {"messages": 1} and back == {}


def test_the_report_shows_live_copy_and_env0_with_what_was_left_out(lists):
    meta = {"homehiro/homehiro.db": {"live": {"setting": 5, "websession": 2, "person": 3},
                                     "copy": {"setting": 3, "websession": 0, "person": 3},
                                     "scrubbed": {"setting": ["ha_token", "ha_url"], "websession": 2},
                                     "check": "ok", "alembic": "abc", "bytes": 2**20},
            "core/db/data.db": {"missing": True}}
    text = data.report(meta, {}, {"homehiro/homehiro.db": {"setting": 4, "websession": 1, "person": 3}},
                       {"homehiro/homehiro.db": {"setting": 1, "websession": 1}})
    assert "not copied: ha_token, ha_url; env0's 1 kept" in text
    assert "2 row(s) not copied; env0's 1 kept" in text
    assert "core/db/data.db: not on Simone" in text
    assert "homehiro: hiroleague, streams, *.before-*" in data.left_out(lists)


def test_a_live_copy_from_before_the_lists_is_refused_before_anything_changes(tmp_path, lists):
    src = tmp_path / "old-copy"
    src.mkdir()
    (src / "counts.json").write_text(json.dumps({"core/workspace.db": {"missing": True}}))

    class Hw:
        class Stop(Exception):
            pass

    with pytest.raises(Hw.Stop, match="fetch a new copy"):
        data.apply(Hw, src, lists)


def test_a_folder_simone_doesnt_have_yet_is_skipped_and_env0s_stays(tmp_path, lists, monkeypatch):
    asked = []

    def ssh(args, **_):
        asked.append(args)
        return "no\n"  # nothing uploaded on live yet

    monkeypatch.setattr(data, "ssh", ssh)

    class Hw:
        @staticmethod
        def data_dir(env):
            return tmp_path / "env0"

        @staticmethod
        def app_data(env, a):
            return tmp_path / "env0" / a.repo

    (tmp_path / "env0" / "studyhiro" / "files").mkdir(parents=True)
    (tmp_path / "env0" / "studyhiro" / "files" / "mine.jpg").write_bytes(b"m")
    lines = data.copy_files(Hw, tmp_path / "archive", lists)
    assert "studyhiro/files: not on Simone, env0's left as it is" in lines
    assert (tmp_path / "env0" / "studyhiro" / "files" / "mine.jpg").read_bytes() == b"m"
    assert not (tmp_path / "archive").exists() and all(a[0] == "test" for a in asked)


def test_a_change_in_an_environment_replaces_its_link_and_leaves_env0s_file(tmp_path, lists):
    env0, env = tmp_path / "env0" / "studyhiro", tmp_path / "env1" / "studyhiro"
    (env0 / "files").mkdir(parents=True)
    (env0 / "files" / "a.jpg").write_bytes(b"env0")
    data.link_pictures(env0, env, "studyhiro", lists)
    # As the backend kit's files.write_bytes does: a new file renamed over the old one
    tmp = env / "files" / ".a.jpg.tmp"
    tmp.write_bytes(b"task")
    tmp.replace(env / "files" / "a.jpg")
    assert (env / "files" / "a.jpg").read_bytes() == b"task" and (env0 / "files" / "a.jpg").read_bytes() == b"env0"


def test_what_no_list_covers_is_found_in_env0_and_live_and_told_to_codehiro(tmp_path, lists, monkeypatch):
    (tmp_path / "env0" / "homehiro" / "tts-cache").mkdir(parents=True)
    (tmp_path / "env0" / "homehiro" / "people").mkdir()
    sent = []

    class Hw:
        @staticmethod
        def data_dir(env):
            return tmp_path / "env0"

        @staticmethod
        def app_data(env, a):
            return tmp_path / "env0" / a.repo

        @staticmethod
        def event(**e):
            sent.append(e)

    monkeypatch.setattr(data, "live_listing", lambda lst, group: ["new-uploads", "studyhiro.db"] if group == "studyhiro" else [])
    monkeypatch.setattr(data, "live_bytes", lambda lst, names: {n: 7 for n in names})
    (tmp_path / "env0" / "homehiro" / "people" / "a.jpg").write_bytes(b"12345")
    found = data.report_drift(Hw, lists)
    assert found == [{"group": "homehiro", "place": "env0", "names": ["tts-cache"]},
                     {"group": "studyhiro", "place": "live", "names": ["new-uploads"]}]
    assert sent[0]["sizes"]["homehiro"] == {"people": 5} and sent[1]["sizes"]["studyhiro"] == {"studyhiro.db": 7}
    assert [(e["step"], e["place"], e["unlisted"]) for e in sent] == [
        ("copy-lists", "env0", [{"group": "homehiro", "names": ["tts-cache"]}]),
        ("copy-lists", "live", [{"group": "studyhiro", "names": ["new-uploads"]}])]
    assert data.said_drift([]) == ["  nothing: every file in the data folders looked at is listed."]


def test_an_apps_setting_the_cores_list_already_covers_is_refused(tmp_path):
    (tmp_path / "hiroleague").mkdir()
    (tmp_path / "hiroleague" / "data.toml").write_text(CORE_LIST, "utf-8")
    (tmp_path / "homehiro").mkdir()
    item = '[[item]]\npath = "a.db"\nkind = "database"\nlive = "copy"\nenvs = "copy"\nwhy = "w"\n'
    for key, extra, says in (("hiroleague_url", "", "already makes it per-place"),  # the kit's key
                             ("tv_key", "", "already makes it per-place"),  # the pattern's (_key$)
                             ("ha_url", 'needs = "reads"\n', None)):  # the pattern's, but needs says more
        (tmp_path / "homehiro" / "data.toml").write_text(
            f'live = "~/h"\n{item}[[setting]]\nkey = "{key}"\n{extra}why = "w"\n', "utf-8")
        if says:
            with pytest.raises(copylist.ListError, match=says):
                copylist.load_all(tmp_path, ["homehiro"])
            assert copylist.main([str(tmp_path / "homehiro")]) == 1  # the commit's check says so too
        else:
            assert copylist.load_all(tmp_path, ["homehiro"])["homehiro"].settings[0].needs == "reads"


def test_a_lists_changes_are_said_and_what_widens_what_live_gives_is_marked():
    head = 'live = "~/h"\n[every_app]\nplace_key_pattern = "_url$"\nplace_keys = []\n'
    old = copylist.parse(head + '[[item]]\npath = "a.db"\nkind = "database"\nlive = "copy"\nenvs = "copy"\n'
                         'place_tables = ["websession"]\nwhy = "w"\n[[item]]\npath = "sounds"\nkind = "folder"\n'
                         'live = "own"\nenvs = "none"\nwhy = "w"\n[[item]]\npath = "old"\nkind = "folder"\nlive = "own"\n'
                         'envs = "none"\nwhy = "w"\n[[setting]]\nkey = "tv_cast"\nwhy = "w"\n', copylist.CORE)
    new = copylist.parse(head + '[[item]]\npath = "a.db"\nkind = "database"\nlive = "copy"\nenvs = "copy"\nwhy = "w"\n'
                         '[[item]]\npath = "sounds"\nkind = "folder"\nlive = "copy"\nenvs = "link"\nwhy = "w"\n'
                         '[[item]]\npath = "memos"\nkind = "folder"\nlive = "copy"\nenvs = "link"\nwhy = "w"\n'
                         '[[setting]]\nkey = "memo_state"\nwhy = "w"\n', copylist.CORE)
    assert copylist.changes(old, new) == [
        ("~ a.db: per-place tables websession -> none", True),  # sessions would now come from live
        ("~ sounds: from live own -> copy; to env1-env5 none -> link", True),
        ("+ memos: from live copy, to env1-env5 link", True),
        ("- old", False),
        ("+ setting memo_state: per place", False),
        ("- setting tv_cast: no longer per place", True),
    ]
    assert all(w for _, w in copylist.changes(None, new) if _.startswith("+ ") and "from live copy" in _)
