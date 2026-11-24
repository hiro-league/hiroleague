"""Phase 9a: an extension's features and rights, and the one check every extension makes.
Permissions phase 1: several roles add up, and a personal right reaches the person's own or everyone's."""

import pytest

from hiro_channel_sdk.access import (
    OWNER_ROLE,
    ExtensionFeature,
    ExtensionRight,
    allowed,
    declared_keys,
    normalize,
    owner_rights,
    reach,
)
from hiro_channel_sdk.extension import ExtensionInfo

FEATURES = [
    ExtensionFeature(id="streams", name="Streams", rights=[
        ExtensionRight(id="see", name="See"),
        ExtensionRight(id="edit", name="Add and change"),
        ExtensionRight(id="delete", name="Delete"),
    ]),
    ExtensionFeature(id="settings", name="Settings", rights=[ExtensionRight(id="change", name="Change")]),
    ExtensionFeature(id="myroom", name="My room", rights=[ExtensionRight(id="use", name="Use")], not_for_owner=True),
]
BY_ID = {f.id: f for f in FEATURES}


def test_declared_keys_in_order():
    assert declared_keys(FEATURES) == ["streams.see", "streams.edit", "streams.delete", "settings.change", "myroom.use"]


def test_normalize_adds_see_and_drops_unknown():
    assert normalize(FEATURES, ["streams.delete", "nope.x", "settings.change"]) == [
        "streams.see", "streams.delete", "settings.change"]


def test_owner_has_everything_but_not_for_owner():
    assert owner_rights(FEATURES) == {"streams.see", "streams.edit", "streams.delete", "settings.change"}
    assert allowed({OWNER_ROLE: []}, "streams", "delete", BY_ID)
    assert not allowed({OWNER_ROLE: []}, "myroom", "use", BY_ID)


def test_others_have_what_was_granted():
    granted = ["streams.see", "myroom.use"]
    assert allowed({"kid": granted}, "streams", "see", BY_ID)
    assert not allowed({"kid": granted}, "streams", "edit", BY_ID)
    assert allowed({"kid": granted}, "myroom", "use", BY_ID)
    assert not allowed({}, "streams", "see", BY_ID)  # no role: waiting or refused
    assert not allowed({"kid": granted}, "unknown", "see", BY_ID)


# Permissions phase 1 -------------------------------------------------------------------------------------------------

# A feature about people's things: its see and build are personal, its run isn't.
PERSONAL = [
    ExtensionFeature(id="auto", name="Automations", rights=[
        ExtensionRight(id="see", name="See", personal=True),
        ExtensionRight(id="build", name="Build", personal=True),
        ExtensionRight(id="run", name="Run"),
    ]),
    ExtensionFeature(id="room", name="My room", rights=[ExtensionRight(id="use", name="Use", personal=True)],
                     not_for_owner=True),
]
P_BY_ID = {f.id: f for f in PERSONAL}


def test_declared_keys_name_own_only_for_personal_rights():
    assert declared_keys(PERSONAL) == ["auto.see", "auto.see:own", "auto.build", "auto.build:own", "auto.run",
                                       "room.use", "room.use:own"]


@pytest.mark.parametrize(("granted", "kept"), [
    (["auto.build:own"], ["auto.see:own", "auto.build:own"]),  # see follows, as far as the grant
    (["auto.build"], ["auto.see", "auto.build"]),
    (["auto.see:own", "auto.build"], ["auto.see", "auto.build"]),  # see reaches at least as far as build
    (["auto.build", "auto.build:own"], ["auto.see", "auto.build"]),  # everyone's covers their own
    (["auto.run:own"], []),  # run isn't personal: its :own key means nothing
    (["auto.run"], ["auto.see", "auto.run"]),
    (["room.use:own", "room.use"], ["room.use"]),
])
def test_normalize_with_reach(granted, kept):
    assert normalize(PERSONAL, granted) == kept


def test_normalize_see_not_personal_reaches_everyone():
    features = [ExtensionFeature(id="f", name="F", rights=[
        ExtensionRight(id="see", name="See"), ExtensionRight(id="edit", name="Edit", personal=True)])]
    assert normalize(features, ["f.edit:own"]) == ["f.see", "f.edit:own"]


@pytest.mark.parametrize(("roles", "feature", "right", "expected"), [
    ({"kid": ["auto.see:own"]}, "auto", "see", "own"),
    ({"kid": ["auto.see:own"], "adult": ["auto.see"]}, "auto", "see", "all"),  # roles add up, the widest wins
    ({"kid": ["auto.build:own"], "adult": ["auto.see"]}, "auto", "build", "own"),
    ({"kid": ["auto.run:own"]}, "auto", "run", "no"),  # an :own key on a right that isn't personal
    ({OWNER_ROLE: [], "kid": []}, "auto", "build", "all"),
    ({OWNER_ROLE: []}, "room", "use", "no"),  # not for the owner
    ({OWNER_ROLE: [], "kid": ["room.use:own"]}, "room", "use", "own"),  # the owner's other role still counts
    ({}, "auto", "see", "no"),
    ({"kid": ["auto.see"]}, "nope", "see", "no"),
])
def test_reach_adds_up_roles(roles, feature, right, expected):
    assert reach(roles, feature, right, P_BY_ID) == expected


def test_allowed_own_needs_the_record_to_be_theirs():
    roles = {"kid": ["auto.see:own"]}
    assert allowed(roles, "auto", "see", P_BY_ID, asker="mark", owners=["mark"])
    assert not allowed(roles, "auto", "see", P_BY_ID, asker="mark", owners=["joe"])
    assert not allowed(roles, "auto", "see", P_BY_ID)  # no record named: only everyone's counts
    assert not allowed(roles, "auto", "see", P_BY_ID, owners=["mark"])  # nobody asking
    assert allowed({"adult": ["auto.see"]}, "auto", "see", P_BY_ID, asker="mark", owners=["joe"])


def test_extension_info_carries_features():
    info = ExtensionInfo(name="x", features=FEATURES)
    again = ExtensionInfo.model_validate(info.model_dump())
    assert again.features[2].not_for_owner and again.features[0].rights[1].name == "Add and change"
