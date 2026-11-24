"""pair_apps.known(): whether an environment's core holds an app's key, read from the extension manager's list."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pair_apps


def _workspace(tmp_path: Path) -> Path:
    db = tmp_path / "db" / "workspace.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as con:
        con.execute("create table extension_records (extension_id text, name text, kind text, public_key text)")
        con.execute("create table extensions (extension_id text, name text)")  # the old list, kept as it was copied
        con.execute("insert into extension_records values ('e-home', 'home', 'app', 'pk'), "
                    "('e-wa', 'whatsapp', 'channel', '')")
        con.execute("insert into extensions values ('e-old', 'home')")
    return tmp_path


def test_an_app_is_known_by_its_row_in_the_one_list(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    assert pair_apps.known(workspace, "e-home")
    # Only the old table has it: not known, so it pairs.
    assert not pair_apps.known(workspace, "e-old")
    assert not pair_apps.known(workspace, "e-wa")  # a row with no key yet
    assert not pair_apps.known(tmp_path / "none", "e-home")


def test_an_app_the_core_already_holds_by_name_pairs_again_on_its_record(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    assert pair_apps.holder(workspace, "home") == "e-home"
    assert pair_apps.holder(workspace, "whatsapp") == ""  # a channel's name is never an app's record
    assert pair_apps.holder(workspace, "net") == ""
    assert pair_apps.holder(tmp_path / "none", "home") == ""
