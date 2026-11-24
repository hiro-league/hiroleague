"""Phase 9a: each role's rights in an extension come from the core; an extension imports its old grants once."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from hirocli.domain.access import CORE_SOURCE, list_sources, roles_with_rights, set_rights
from hirocli.domain.extensions import add_paired_extension, touch_paired_extension
from hirocli.domain.core_features import every_core_key
from hirocli.domain.people import PeopleError, get_role
from hirocli.runtime.people_for_extensions import handle_people_list, handle_roles_import_rights
from hirocli.runtime.request_handler import RequestRefused

FEATURES = [
    {"id": "streams", "name": "Streams", "rights": [
        {"id": "see", "name": "See"}, {"id": "edit", "name": "Add and change"}, {"id": "delete", "name": "Delete"}]},
    {"id": "myroom", "name": "My room", "rights": [{"id": "use", "name": "Use"}], "not_for_owner": True},
]
INFO = {"name": "home", "features": FEATURES, "offers": {"shows": [{"title": "Home", "url": "http://x"}]}}


def _ctx(workspace: Path) -> SimpleNamespace:
    home = add_paired_extension(workspace, name="home", public_key="k", info=INFO)
    return SimpleNamespace(
        server_ctx=SimpleNamespace(workspace_path=workspace, extension_manager=None),
        workspace_path=workspace,
        msg=SimpleNamespace(routing=SimpleNamespace(sender_id=home.extension_id)),
    )


def test_sources_are_hiroleague_then_each_extension_with_features(tmp_path: Path) -> None:
    add_paired_extension(tmp_path, name="home", public_key="k", info=INFO)
    add_paired_extension(tmp_path, name="quiet", public_key="k2", info={"name": "quiet"})
    sources = list_sources(tmp_path)
    assert [(s.id, s.name) for s in sources] == [(CORE_SOURCE, "HiroLeague"), ("home", "Home")]


def test_set_rights_adds_see_refuses_unknown_and_owner(tmp_path: Path) -> None:
    add_paired_extension(tmp_path, name="home", public_key="k", info=INFO)
    assert set_rights(tmp_path, "adult", "home", ["streams.delete"]).rights == {"home": ["streams.see", "streams.delete"]}
    with pytest.raises(PeopleError, match="no right called"):
        set_rights(tmp_path, "adult", "home", ["streams.fly"])
    with pytest.raises(PeopleError, match="owner"):
        set_rights(tmp_path, "owner", "home", [])


def test_the_cores_own_grants_are_kept_like_an_apps(tmp_path: Path) -> None:
    """Permissions phase 2: the core's features are a source like an app's; see follows, as far as the grant."""
    assert set_rights(tmp_path, "adult", CORE_SOURCE, ["memories.change:own", "logs.see"]).rights == {
        CORE_SOURCE: ["memories.see:own", "memories.change:own", "logs.see"]}
    assert not get_role(tmp_path, "adult").admin  # the Phase 8 switch is not written by a grant
    with pytest.raises(PeopleError, match="no right called"):
        set_rights(tmp_path, "adult", CORE_SOURCE, ["admin.open"])
    with pytest.raises(PeopleError, match="isn't about people's own things"):
        set_rights(tmp_path, "adult", CORE_SOURCE, ["logs.see:own"])


def test_roles_with_rights_owner_has_all_but_not_for_owner(tmp_path: Path) -> None:
    add_paired_extension(tmp_path, name="home", public_key="k", info=INFO)
    roles = {r["role_id"]: r["rights"] for r in roles_with_rights(tmp_path)}
    assert roles["owner"] == {CORE_SOURCE: every_core_key(), "home": ["streams.see", "streams.edit", "streams.delete"]}
    assert roles["kid"] == {CORE_SOURCE: [], "home": []}


def test_people_list_carries_the_callers_rights_and_says(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    set_rights(tmp_path, "kid", "home", ["myroom.use"])
    roles = {r["role_id"]: r for r in asyncio.run(handle_people_list({}, ctx))["roles"]}
    assert roles["kid"]["rights"] == ["myroom.use"] and roles["kid"]["says"] == ""
    assert roles["owner"]["rights"] == ["streams.see", "streams.edit", "streams.delete"]


def test_an_app_taking_features_over_copies_each_roles_rights_once(tmp_path: Path) -> None:
    """Phase 9b: NetHiro takes System health from Home; each role keeps exactly what it had there."""
    add_paired_extension(tmp_path, name="home", public_key="k", info=INFO)
    net = add_paired_extension(tmp_path, name="net", public_key="k2", info={"name": "net", "features": [
        {"id": "streams", "name": "Streams", "rights": [{"id": "see", "name": "See"}, {"id": "delete", "name": "Delete"}]}]})
    set_rights(tmp_path, "adult", "home", ["streams.see", "streams.edit", "streams.delete", "myroom.use"])
    set_rights(tmp_path, "kid", "net", ["streams.see"])  # already set there: kept
    ctx = SimpleNamespace(server_ctx=SimpleNamespace(workspace_path=tmp_path, extension_manager=None), workspace_path=tmp_path,
                          msg=SimpleNamespace(routing=SimpleNamespace(sender_id=net.extension_id)))
    assert asyncio.run(handle_roles_import_rights({"copy_from": "home"}, ctx)) == {"imported": ["adult"]}
    assert get_role(tmp_path, "adult").rights["net"] == ["streams.see", "streams.delete"]
    assert get_role(tmp_path, "kid").rights["net"] == ["streams.see"]
    assert asyncio.run(handle_roles_import_rights({"copy_from": "home"}, ctx)) == {"imported": []}


def test_import_fills_only_roles_without_rights_there(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    set_rights(tmp_path, "adult", "home", ["streams.see"])
    answer = asyncio.run(handle_roles_import_rights({"roles": {
        "adult": {"rights": ["streams.edit"], "says": "Parents"},
        "kid": {"rights": ["myroom.use", "streams.nope"], "says": "Kids"},
        "owner": {"rights": []},
        "ghost": {"rights": ["streams.see"]},
    }}, ctx))
    assert answer == {"imported": ["kid"]}
    assert get_role(tmp_path, "adult").rights["home"] == ["streams.see"]  # the admin's choice stays
    assert get_role(tmp_path, "adult").says == "Parents"  # an empty line is filled
    assert get_role(tmp_path, "kid").rights["home"] == ["myroom.use"]
    again = asyncio.run(handle_roles_import_rights({"roles": {"kid": {"rights": []}}}, ctx))
    assert again == {"imported": []}


# Permissions phase 1: a right an app declares personal is granted for their own or for everyone's.
PERSONAL_INFO = {"name": "study", "features": [
    {"id": "study", "name": "Study", "rights": [
        {"id": "see", "name": "See", "personal": True}, {"id": "add", "name": "Add", "personal": True},
        {"id": "grade", "name": "Grade"}]},
]}


def test_a_personal_right_is_granted_for_their_own_or_everyones(tmp_path: Path) -> None:
    add_paired_extension(tmp_path, name="study", public_key="k", info=PERSONAL_INFO)
    assert set_rights(tmp_path, "kid", "study", ["study.add:own"]).rights["study"] == ["study.see:own", "study.add:own"]
    assert set_rights(tmp_path, "adult", "study", ["study.add:own", "study.see"]).rights["study"] == [
        "study.see", "study.add:own"]
    with pytest.raises(PeopleError, match="isn't about people's own things"):
        set_rights(tmp_path, "kid", "study", ["study.grade:own"])
    roles = {r["role_id"]: r["rights"] for r in roles_with_rights(tmp_path)}
    assert roles["kid"]["study"] == ["study.see:own", "study.add:own"]
    assert roles["owner"]["study"] == ["study.see", "study.add", "study.grade"]  # the owner's reach everyone's


def test_existing_grants_keep_their_meaning(tmp_path: Path) -> None:
    """A plain key granted before a right was declared personal still reaches everyone's: nothing is rewritten."""
    add_paired_extension(tmp_path, name="home", public_key="k", info=INFO)
    set_rights(tmp_path, "kid", "home", ["streams.see", "myroom.use"])
    personal = {**INFO, "features": [{**f, "rights": [{**r, "personal": True} for r in f["rights"]]} for f in FEATURES]}
    add_paired_extension(tmp_path, name="home", public_key="k", info=personal)
    roles = {r["role_id"]: r["rights"] for r in roles_with_rights(tmp_path)}
    assert roles["kid"]["home"] == ["streams.see", "myroom.use"]


# Permissions phase 6: HomeHiro renames its permissions to the standard and groups Dashboard in an area.
RENAMED_INFO = {"name": "home", "areas": {"dashboard": "Dashboard", "bad": 3}, "features": [
    {"id": "dashboard.control", "name": "Control", "rights": [{"id": "see", "name": "See"}, {"id": "switch", "name": "Switch"}]},
    {"id": "streams", "name": "Streams", "rights": [
        {"id": "see", "name": "See"}, {"id": "change", "name": "Add and change"}, {"id": "delete", "name": "Delete"}]},
    {"id": "myroom", "name": "My room", "not_for_owner": True, "rights": [
        {"id": "see", "name": "See", "personal": True}, {"id": "switch", "name": "Switch", "personal": True}]},
]}
RENAMED = {"streams.edit": ["streams.change"], "myroom.use": ["myroom.see:own", "myroom.switch:own"]}


def test_renamed_rights_move_once_beside_the_old_keys(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    set_rights(tmp_path, "adult", "home", ["streams.see", "streams.edit"])
    set_rights(tmp_path, "kid", "home", ["myroom.use"])
    touch_paired_extension(tmp_path, ctx.msg.routing.sender_id, info=RENAMED_INFO)
    assert asyncio.run(handle_roles_import_rights({"renamed": RENAMED}, ctx)) == {"imported": ["adult", "kid"]}
    # the old keys stay stored, for the release before; read, a role has the new ones only, meaning what they meant
    assert get_role(tmp_path, "kid").rights["home"] == ["myroom.use", "myroom.see:own", "myroom.switch:own"]
    roles = {r["role_id"]: r["rights"]["home"] for r in roles_with_rights(tmp_path)}
    assert roles["kid"] == ["myroom.see:own", "myroom.switch:own"]
    assert roles["adult"] == ["streams.see", "streams.change"]
    assert asyncio.run(handle_roles_import_rights({"renamed": RENAMED}, ctx)) == {"imported": []}  # asked again: nothing
    # a save keeps the new keys only
    assert set_rights(tmp_path, "kid", "home", roles["kid"]).rights["home"] == ["myroom.see:own", "myroom.switch:own"]


def test_a_rename_to_a_key_the_app_doesnt_declare_or_from_one_it_still_does_is_refused(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    touch_paired_extension(tmp_path, ctx.msg.routing.sender_id, info=RENAMED_INFO)
    with pytest.raises(RequestRefused, match="doesn't declare"):
        asyncio.run(handle_roles_import_rights({"renamed": {"streams.edit": ["streams.nope"]}}, ctx))
    with pytest.raises(RequestRefused, match="still declares"):
        asyncio.run(handle_roles_import_rights({"renamed": {"streams.see": ["streams.change"]}}, ctx))
    with pytest.raises(RequestRefused, match="renamed must be"):
        asyncio.run(handle_roles_import_rights({"renamed": ["streams.edit"]}, ctx))


def test_an_apps_areas_reach_the_roles_page(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    touch_paired_extension(tmp_path, ctx.msg.routing.sender_id, info=RENAMED_INFO)
    home = next(s for s in list_sources(tmp_path) if s.id == "home")
    assert home.areas == {"dashboard": "Dashboard"}  # anything but text is skipped
