"""Permissions phase 1: a person holds one or several roles; people.role_id stays the first of them."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hirocli.domain.access import CORE_SOURCE, admin_access, set_rights
from hirocli.domain.core_features import every_core_key
from hirocli.domain.db import _give_core_to_admin_roles
from hirocli.domain.people import (
    PeopleError,
    add_person,
    add_role,
    get_person,
    list_people,
    list_roles,
    remove_person,
    remove_role,
    update_person,
)


def _stored_role_id(workspace: Path, person_id: str) -> str:
    with sqlite3.connect(workspace / "db" / "workspace.db") as conn:
        return conn.execute("SELECT role_id FROM people WHERE person_id = ?", (person_id,)).fetchone()[0]


def test_a_person_holds_several_roles_in_the_roles_order(tmp_path: Path) -> None:
    mark = add_person(tmp_path, name="Mark", role_ids=["kid", "adult"])
    assert mark.role_ids == ["adult", "kid"] and mark.role_id == "adult"
    assert get_person(tmp_path, mark.person_id).role_ids == ["adult", "kid"]
    assert _stored_role_id(tmp_path, mark.person_id) == "adult"  # what an app reads until phase 5


def test_owner_is_always_first(tmp_path: Path) -> None:
    michel = add_person(tmp_path, name="Michel", role_ids=["kid", "owner"])
    assert michel.role_ids == ["owner", "kid"] and michel.role_id == "owner"


def test_a_person_keeps_at_least_one_known_role(tmp_path: Path) -> None:
    with pytest.raises(PeopleError, match="at least one role"):
        add_person(tmp_path, name="Mark", role_ids=[])
    with pytest.raises(PeopleError, match="no role"):
        add_person(tmp_path, name="Mark", role_ids=["kid", "pilot"])
    mark = add_person(tmp_path, name="Mark", role_ids=["kid"])
    with pytest.raises(PeopleError, match="at least one role"):
        update_person(tmp_path, mark.person_id, role_ids=[])


def test_setting_roles_replaces_them_and_moves_the_first(tmp_path: Path) -> None:
    mark = add_person(tmp_path, name="Mark", role_ids=["kid"])
    assert update_person(tmp_path, mark.person_id, role_ids=["kid", "adult"]).role_ids == ["adult", "kid"]
    assert _stored_role_id(tmp_path, mark.person_id) == "adult"
    assert update_person(tmp_path, mark.person_id, role_ids=["kid"]).role_ids == ["kid"]
    assert _stored_role_id(tmp_path, mark.person_id) == "kid"


def test_one_role_from_an_app_keeps_or_replaces(tmp_path: Path) -> None:
    """An app that knows one role sends role_id: their first role changes nothing, another becomes the only one."""
    mark = add_person(tmp_path, name="Mark", role_ids=["adult", "kid"])
    assert update_person(tmp_path, mark.person_id, role_id="adult", name="Marky").role_ids == ["adult", "kid"]
    assert update_person(tmp_path, mark.person_id, role_id="kid").role_ids == ["kid"]


def test_the_only_owner_keeps_owner_even_with_other_roles(tmp_path: Path) -> None:
    michel = add_person(tmp_path, name="Michel", role_ids=["owner", "adult"])
    with pytest.raises(PeopleError, match="only Owner"):
        update_person(tmp_path, michel.person_id, role_ids=["adult"])
    with pytest.raises(PeopleError, match="only Owner"):
        remove_person(tmp_path, michel.person_id)
    mona = add_person(tmp_path, name="Mona", role_ids=["adult", "owner"])  # a second owner, by a second role
    assert update_person(tmp_path, michel.person_id, role_ids=["adult"]).role_ids == ["adult"]
    assert mona.role_id == "owner"


def test_a_role_held_as_a_second_role_cant_be_removed(tmp_path: Path) -> None:
    add_role(tmp_path, "Guest")
    add_person(tmp_path, name="Mark", role_ids=["kid", "guest"])
    with pytest.raises(PeopleError, match="still given to Mark"):
        remove_role(tmp_path, "guest")


def test_removing_a_person_removes_their_roles(tmp_path: Path) -> None:
    add_role(tmp_path, "Guest")
    mark = add_person(tmp_path, name="Mark", role_ids=["kid", "guest"])
    remove_person(tmp_path, mark.person_id)
    remove_role(tmp_path, "guest")  # nobody holds it any more


def test_the_admin_opens_by_any_roles_core_permissions(tmp_path: Path) -> None:
    """Permissions phase 2: a person's roles add up; only a grant for everyone's opens a page of the admin."""
    set_rights(tmp_path, "adult", CORE_SOURCE, ["logs.see"])
    set_rights(tmp_path, "kid", CORE_SOURCE, ["assistant.talk", "conversations.see:own", "memories.see:own"])
    both = admin_access(tmp_path, ["kid", "adult"])
    assert not both.owner and both.opens_admin
    assert both.levels["logs"] == "see" and both.levels["logs.runs"] == "no" and both.levels["conversations"] == "no"
    assert both.keys == ["assistant.talk", "conversations.see:own", "memories.see:own", "logs.see"]
    assert not admin_access(tmp_path, ["kid"]).opens_admin
    owner = admin_access(tmp_path, ["owner"])
    assert owner.owner and set(owner.levels.values()) == {"use"}
    assert not admin_access(tmp_path, ["nobody"]).opens_admin


def _admin_switch_on(workspace: Path, role_id: str) -> None:
    """A role as Phase 8 left it: its switch on, nothing in the core yet."""
    with sqlite3.connect(workspace / "db" / "workspace.db") as conn:
        conn.execute("UPDATE roles SET admin = 1, rights = '{}' WHERE role_id = ?", (role_id,))


def _give_once(workspace: Path) -> list[str]:
    conn = sqlite3.connect(workspace / "db" / "workspace.db", isolation_level=None)
    try:
        return _give_core_to_admin_roles(conn)
    finally:
        conn.close()


def test_a_role_that_opened_the_admin_gets_every_core_permission_once(tmp_path: Path) -> None:
    get_person(tmp_path, "nobody")  # makes the workspace
    _admin_switch_on(tmp_path, "adult")
    assert _give_once(tmp_path) == ["adult"]
    adult = {r.role_id: r for r in list_roles(tmp_path)}["adult"]
    assert adult.rights[CORE_SOURCE] == every_core_key()
    assert {r.role_id: r.rights.get(CORE_SOURCE) for r in list_roles(tmp_path)}["kid"] is None  # the switch was off
    set_rights(tmp_path, "adult", CORE_SOURCE, ["logs.see"])  # Michel narrows it on the Roles page
    assert _give_once(tmp_path) == []
    assert {r.role_id: r for r in list_roles(tmp_path)}["adult"].rights[CORE_SOURCE] == ["logs.see"]


def test_people_from_before_hold_their_one_role(tmp_path: Path) -> None:
    """A workspace an older release wrote (people.role_id only): every person holds that role, and nothing in
    people or roles is rewritten."""
    db = tmp_path / "db" / "workspace.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE roles (role_id TEXT PRIMARY KEY, name TEXT NOT NULL, built_in INTEGER NOT NULL "
                     "DEFAULT 0, position INTEGER NOT NULL DEFAULT 0)")
        conn.execute("CREATE TABLE people (person_id TEXT PRIMARY KEY, name TEXT NOT NULL, role_id TEXT NOT NULL)")
        conn.executemany("INSERT INTO roles VALUES (?, ?, ?, ?)",
                         [("owner", "Owner", 1, 0), ("adult", "Adult", 0, 1), ("kid", "Kid", 0, 2)])
        conn.executemany("INSERT INTO people VALUES (?, ?, ?)", [("p1", "Michel", "owner"), ("p2", "Mark", "kid")])
    people = {p.name: p for p in list_people(tmp_path)}
    assert people["Michel"].role_ids == ["owner"] and people["Mark"].role_ids == ["kid"]
    with sqlite3.connect(db) as conn:
        assert sorted(conn.execute("SELECT person_id, role_id FROM people")) == [("p1", "owner"), ("p2", "kid")]
        assert sorted(conn.execute("SELECT person_id, role_id FROM person_roles")) == [("p1", "owner"), ("p2", "kid")]


def test_a_role_changed_by_an_older_release_is_the_one_they_hold(tmp_path: Path) -> None:
    """Back to an older release by hand, on this database: it changes only people.role_id. On the next start of this
    release that person holds that one role, and everyone else keeps theirs."""
    from hirocli.domain.db import _fill_person_roles

    mark = add_person(tmp_path, name="Mark", role_ids=["adult", "kid"])
    mona = add_person(tmp_path, name="Mona", role_ids=["adult", "kid"])
    db = tmp_path / "db" / "workspace.db"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE people SET role_id = 'owner' WHERE person_id = ?", (mark.person_id,))  # the older release
        assert _fill_person_roles(conn) == 1
    assert get_person(tmp_path, mark.person_id).role_ids == ["owner"]
    assert get_person(tmp_path, mona.person_id).role_ids == ["adult", "kid"]
