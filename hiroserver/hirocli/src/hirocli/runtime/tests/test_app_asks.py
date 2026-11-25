"""Permissions phase 8: every app ask is held to the SDK's table, the app's approvals and the person's proof
(runtime/app_asks.py). The contract: every method an app may call has its row."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from hiro_channel_sdk.approvals import (
    APP_METHODS,
    NOT_ALLOWED,
    NOT_APPROVED,
    PARAM_SIGNED_IN,
    PEOPLE_ACT,
    PEOPLE_SEE,
    SIGN_IN_AGAIN,
    ApprovedItem,
)

from hirocli.domain import approvals, person_tokens
from hirocli.domain.extensions import add_paired_extension
from hirocli.domain.people import add_person
from hirocli.runtime import app_asks
from hirocli.runtime.people_for_extensions import handle_people_add, handle_people_update
from hirocli.runtime.request_handler import CALLER_EXTENSION, RequestRefused
from hirocli.runtime.request_methods import _REGISTERED_HANDLERS

INFO = {"name": "home", "offers": {"shows": [{"kind": "site", "title": "Home", "url": "http://home.hiro.local"}]}}


def test_every_method_an_app_may_call_has_its_row_in_the_table() -> None:
    open_to_apps = {name for name, _fn, callers in _REGISTERED_HANDLERS if CALLER_EXTENSION in callers}
    assert open_to_apps == set(APP_METHODS), "a core method an app may call names what it needs in the SDK's table"


def _app(workspace: Path, approved: list[ApprovedItem] | None) -> str:
    app = add_paired_extension(workspace, name="home", public_key="k", info=INFO)
    approvals.write(workspace, app.extension_id, approved)
    return app.extension_id


def _refused(workspace: Path, app: str, method: str, params: dict | None = None) -> app_asks.AppRefused:
    with pytest.raises(app_asks.AppRefused) as caught:
        app_asks.check(workspace, app, method, dict(params or {}))
    return caught.value


def test_an_app_from_before_approvals_does_what_it_did_but_never_the_roles(tmp_path: Path) -> None:
    app = _app(tmp_path, None)
    for method in ("people.list", "whatsapp.send", "people.update", "ai.uses.set", "notify", "extensions.ask"):
        assert app_asks.check(tmp_path, app, method, {"to": "net"}).person_id == ""
    assert _refused(tmp_path, app, "roles.add").code == NOT_ALLOWED


def test_an_app_is_refused_what_it_was_not_approved_for_in_words(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    refused = _refused(tmp_path, app, "people.list")
    assert refused.code == NOT_APPROVED
    assert refused.data["permission"] == PEOPLE_SEE and "Extensions page" in refused.message
    approvals.write(tmp_path, app, [ApprovedItem(permission=PEOPLE_SEE)])
    assert app_asks.check(tmp_path, app, "people.list", {}).person_id == ""


def test_an_approved_app_never_sends_to_a_raw_number_on_its_own(tmp_path: Path) -> None:
    app = _app(tmp_path, [ApprovedItem(permission=PEOPLE_SEE)])
    assert _refused(tmp_path, app, "whatsapp.send", {"to": "201000000001"}).code == NOT_ALLOWED


def test_an_ask_to_another_app_is_approved_per_app_asked(tmp_path: Path) -> None:
    app = _app(tmp_path, [ApprovedItem(permission="apps.ask", subject="net")])
    assert app_asks.check(tmp_path, app, "extensions.ask", {"to": "net"}).person_id == ""
    assert _refused(tmp_path, app, "extensions.ask", {"to": "study"}).data["subject"] == "study"


def test_a_person_through_an_app_is_held_to_their_rights_with_the_core_s_proof(tmp_path: Path) -> None:
    owner = add_person(tmp_path, name="Michel", role_id="owner")
    kid = add_person(tmp_path, name="Mark", role_id="kid")
    app = _app(tmp_path, [ApprovedItem(permission=PEOPLE_ACT)])
    as_owner = {PARAM_SIGNED_IN: person_tokens.issue(tmp_path, owner.person_id, app)}
    params = dict(as_owner)
    assert app_asks.check(tmp_path, app, "people.update", params).person_id == owner.person_id
    assert PARAM_SIGNED_IN not in params  # the proof never reaches the method's handler
    as_kid = {PARAM_SIGNED_IN: person_tokens.issue(tmp_path, kid.person_id, app)}
    assert _refused(tmp_path, app, "people.update", as_kid).code == NOT_ALLOWED
    assert _refused(tmp_path, app, "people.update", {}).code == SIGN_IN_AGAIN  # no proof: not the app's to do


def test_a_proof_works_only_for_the_app_it_was_given_to_and_an_app_approved_to_act(tmp_path: Path) -> None:
    owner = add_person(tmp_path, name="Michel", role_id="owner")
    app = _app(tmp_path, [ApprovedItem(permission=PEOPLE_ACT)])
    other = add_paired_extension(tmp_path, name="net", public_key="k2", info={"name": "net"}).extension_id
    approvals.write(tmp_path, other, [ApprovedItem(permission=PEOPLE_ACT)])
    token = person_tokens.issue(tmp_path, owner.person_id, app)
    assert _refused(tmp_path, other, "people.update", {PARAM_SIGNED_IN: token}).code == SIGN_IN_AGAIN
    approvals.write(tmp_path, app, [])
    assert _refused(tmp_path, app, "people.update", {PARAM_SIGNED_IN: token}).data["permission"] == PEOPLE_ACT
    person_tokens.end(tmp_path, token, app)
    approvals.write(tmp_path, app, [ApprovedItem(permission=PEOPLE_ACT)])
    assert _refused(tmp_path, app, "people.update", {PARAM_SIGNED_IN: token}).code == SIGN_IN_AGAIN


def test_a_refusal_is_said_once_per_app_and_item_until_it_connects_again(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    refused = _refused(tmp_path, app, "people.list")
    assert app_asks.said_once(app, refused) and not app_asks.said_once(app, refused)
    app_asks.forget(app)
    assert app_asks.said_once(app, refused)


def _people_ctx(workspace: Path) -> SimpleNamespace:
    home = add_paired_extension(workspace, name="home", public_key="k", info={"name": "home"})
    return SimpleNamespace(server_ctx=SimpleNamespace(workspace_path=workspace, extension_manager=None),
                           workspace_path=workspace, msg=SimpleNamespace(routing=SimpleNamespace(sender_id=home.extension_id)))


def test_no_ask_through_an_app_gives_or_takes_the_owner_role(tmp_path: Path) -> None:
    owner = add_person(tmp_path, name="Michel", role_id="owner")
    joe = add_person(tmp_path, name="Joe", role_id="adult")
    ctx = _people_ctx(tmp_path)
    for ask, params in ((handle_people_update, {"person_id": joe.person_id, "role_ids": ["owner", "adult"]}),
                        (handle_people_update, {"person_id": owner.person_id, "role_ids": ["adult"]}),
                        (handle_people_add, {"name": "Zoe", "role_id": "owner"})):
        with pytest.raises(RequestRefused) as caught:
            asyncio.run(ask(params, ctx))
        assert caught.value.code == "not_allowed" and "Owner role" in caught.value.message
    kept = asyncio.run(handle_people_update({"person_id": owner.person_id, "role_ids": ["owner", "adult"]}, ctx))
    assert kept["person"]["role_ids"][0] == "owner"  # the Owner keeps the role while others change


def test_hiro_reads_only_the_apps_approved_to_tell_it(tmp_path: Path) -> None:
    from hiro_channel_sdk.approvals import HIRO_TELL

    from hirocli.tools.extension_state import _approved_to_tell

    old = _app(tmp_path, None)
    told = add_paired_extension(tmp_path, name="net", public_key="k2", info={"name": "net"}).extension_id
    approvals.write(tmp_path, told, [ApprovedItem(permission=HIRO_TELL)])
    silent = add_paired_extension(tmp_path, name="train", public_key="k3", info={"name": "train"}).extension_id
    approvals.write(tmp_path, silent, [])
    assert _approved_to_tell(tmp_path, [old, told, silent, "gone"]) == {old, told}
