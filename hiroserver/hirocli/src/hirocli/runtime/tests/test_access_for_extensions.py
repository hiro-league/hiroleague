"""Phase 9a: each role's rights in an extension come from the core; an extension imports its old grants once."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from hirocli.domain.access import CORE_SOURCE, list_sources, roles_with_rights, set_rights
from hirocli.domain.extensions import add_paired_extension
from hirocli.domain.people import PeopleError, get_role, set_role_admin
from hirocli.runtime.people_for_extensions import handle_people_list, handle_roles_import_rights

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


def test_hiroleague_open_is_the_admin_switch(tmp_path: Path) -> None:
    set_rights(tmp_path, "adult", CORE_SOURCE, ["admin.open"])
    assert get_role(tmp_path, "adult").admin
    set_rights(tmp_path, "adult", CORE_SOURCE, [])
    assert not get_role(tmp_path, "adult").admin


def test_roles_with_rights_owner_has_all_but_not_for_owner(tmp_path: Path) -> None:
    add_paired_extension(tmp_path, name="home", public_key="k", info=INFO)
    set_role_admin(tmp_path, "kid", False)
    roles = {r["role_id"]: r["rights"] for r in roles_with_rights(tmp_path)}
    assert roles["owner"] == {CORE_SOURCE: ["admin.open"], "home": ["streams.see", "streams.edit", "streams.delete"]}
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
