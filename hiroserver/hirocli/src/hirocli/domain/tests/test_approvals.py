"""Permissions phase 8: what an app is approved for, its rules and where it is kept (domain/approvals.py)."""

from __future__ import annotations

from pathlib import Path

from hiro_channel_sdk.approvals import AI_SEARCH, AI_USE, APPS_ASK, PEOPLE_SEE, SITE_ADDRESS, SITE_NAME, ApprovedItem

from hirocli.domain import approvals
from hirocli.domain.extensions import add_paired_extension

SITE = {"kind": "site", "title": "Home", "url": "http://home.hiro.local"}


def _info(*asks: dict, url: str = "http://home.hiro.local") -> dict:
    return {"name": "home", "offers": {"shows": [{**SITE, "url": url}]}, "asks": list(asks)}


def _keys(items: list[ApprovedItem] | None) -> set[tuple[str, str]]:
    return {(i.permission, i.subject) for i in items or []}


def test_a_declaration_without_asks_asks_nothing_known_and_changes_nothing() -> None:
    assert approvals.asked({"name": "home"}, []) is None
    approved = [ApprovedItem(permission=PEOPLE_SEE)]
    assert approvals.settled(None, approved) == approved  # a kit from before: a rollback drops nothing
    assert approvals.settled(None, None) is None


def test_what_a_declaration_asks_holds_its_address_and_its_lan_names() -> None:
    items = approvals.asked(_info({"permission": PEOPLE_SEE}, {"permission": APPS_ASK, "to": "net"}), ["home.hiro.local:8100"])
    assert [(a.permission, a.subject) for a in items or []] == [
        (PEOPLE_SEE, ""), (APPS_ASK, "net"), (SITE_ADDRESS, "http://home.hiro.local"), (SITE_NAME, "home.hiro.local:8100"),
    ]


def test_an_app_from_before_is_approved_for_everything_until_it_declares_then_for_exactly_that() -> None:
    assert approvals.covers(None, "anything")
    items = approvals.asked(_info({"permission": PEOPLE_SEE}), [])
    first = approvals.settled(items, None)
    assert _keys(first) == {(PEOPLE_SEE, ""), (SITE_ADDRESS, "http://home.hiro.local")}
    assert approvals.waiting(items, first) == []  # nothing it uses waits


def test_a_new_version_s_extras_wait_and_what_it_drops_goes_at_once() -> None:
    approved = [ApprovedItem(permission=PEOPLE_SEE), ApprovedItem(permission=AI_USE),
                ApprovedItem(permission=SITE_ADDRESS, subject="http://home.hiro.local")]
    items = approvals.asked(_info({"permission": PEOPLE_SEE}, {"permission": AI_SEARCH, "required": False}), [])
    after = approvals.settled(items, approved)
    assert _keys(after) == {(PEOPLE_SEE, ""), (SITE_ADDRESS, "http://home.hiro.local")}  # ai.use no longer asked
    assert [(a.permission, a.required) for a in approvals.waiting(items, after)] == [(AI_SEARCH, False)]


def test_a_new_address_waits_and_the_approved_one_stays_in_use() -> None:
    approved = [ApprovedItem(permission=SITE_ADDRESS, subject="http://home.hiro.local")]
    items = approvals.asked(_info(url="http://house.hiro.local"), [])
    after = approvals.settled(items, approved)
    assert approvals.covers(after, SITE_ADDRESS, "http://home.hiro.local")
    assert [(a.permission, a.subject) for a in approvals.waiting(items, after)] == [(SITE_ADDRESS, "http://house.hiro.local")]
    # The owner's yes: the new address replaces the old
    yes = approvals.approve(items, after, set())
    assert _keys(yes) == {(SITE_ADDRESS, "http://house.hiro.local")}


def test_approving_takes_every_required_item_and_the_optional_ones_switched_on() -> None:
    items = approvals.asked(_info({"permission": PEOPLE_SEE}, {"permission": AI_USE, "required": False},
                                  {"permission": AI_SEARCH, "required": False}), [])
    yes = approvals.approve(items or [], [], {(AI_USE, "")})
    assert _keys(yes) == {(PEOPLE_SEE, ""), (AI_USE, ""), (SITE_ADDRESS, "http://home.hiro.local")}


def test_an_unknown_permission_is_shown_but_never_approved() -> None:
    items = approvals.asked(_info({"permission": "memories.see"}), [])
    unknown = next(a for a in items or [] if a.permission == "memories.see")
    assert not unknown.understood and "not understood" in unknown.words
    assert (("memories.see", "")) not in _keys(approvals.approve(items or [], [], {("memories.see", "")}))


def test_a_new_pairing_is_approved_for_nothing_and_its_record_keeps_the_owner_s_answer(tmp_path: Path) -> None:
    info = _info({"permission": PEOPLE_SEE}, {"permission": AI_USE, "required": False})
    home = add_paired_extension(tmp_path, name="home", public_key="k", info=info)
    approvals.keep(tmp_path, home.extension_id, info, new=True)
    view = approvals.view(tmp_path, home.extension_id)
    assert view is not None and view.pending and view.waits
    approved, claims = approvals.approve_app(tmp_path, home.extension_id, set())
    assert _keys(approved) == {(PEOPLE_SEE, ""), (SITE_ADDRESS, "http://home.hiro.local")} and claims == []
    after = approvals.view(tmp_path, home.extension_id)
    assert after is not None and not after.pending and not after.waits  # the optional one left off waits no more


def test_a_paired_app_from_before_keeps_everything_until_its_first_declaration(tmp_path: Path) -> None:
    home = add_paired_extension(tmp_path, name="home", public_key="k", info={"name": "home"})
    assert approvals.read(tmp_path, home.extension_id) == approvals.Approval(approved=None)
    approvals.keep(tmp_path, home.extension_id, {"name": "home"})  # an old kit's declaration: nothing changes
    assert approvals.read(tmp_path, home.extension_id).approved is None  # type: ignore[union-attr]
    approvals.keep(tmp_path, home.extension_id, _info({"permission": PEOPLE_SEE}))
    assert _keys(approvals.read(tmp_path, home.extension_id).approved) == {  # type: ignore[union-attr]
        (PEOPLE_SEE, ""), (SITE_ADDRESS, "http://home.hiro.local")}


def test_a_lan_name_asked_for_waits_and_is_claimed_once_approved(tmp_path: Path) -> None:
    info = _info({"permission": PEOPLE_SEE})
    home = add_paired_extension(tmp_path, name="home", public_key="k", info=info)
    approvals.keep(tmp_path, home.extension_id, info, new=True)
    approvals.set_asked_claim(tmp_path, home.extension_id, "home.hiro.local:8100")
    view = approvals.view(tmp_path, home.extension_id)
    assert view is not None and any(i.permission == SITE_NAME and i.waiting for i in view.items)
    _approved, claims = approvals.approve_app(tmp_path, home.extension_id)
    assert claims == ["home.hiro.local:8100"]
    assert approvals.read(tmp_path, home.extension_id).asked_claim == ""  # type: ignore[union-attr]
