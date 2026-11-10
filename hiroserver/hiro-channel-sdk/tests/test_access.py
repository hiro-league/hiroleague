"""Phase 9a: an extension's features and rights, and the one check every extension makes."""

from hiro_channel_sdk.access import (
    OWNER_ROLE,
    ExtensionFeature,
    ExtensionRight,
    allowed,
    declared_keys,
    normalize,
    owner_rights,
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
    assert allowed(OWNER_ROLE, [], "streams", "delete", BY_ID)
    assert not allowed(OWNER_ROLE, [], "myroom", "use", BY_ID)


def test_others_have_what_was_granted():
    granted = ["streams.see", "myroom.use"]
    assert allowed("kid", granted, "streams", "see", BY_ID)
    assert not allowed("kid", granted, "streams", "edit", BY_ID)
    assert allowed("kid", granted, "myroom", "use", BY_ID)
    assert not allowed(None, granted, "streams", "see", BY_ID)
    assert not allowed("kid", granted, "unknown", "see", BY_ID)


def test_extension_info_carries_features():
    info = ExtensionInfo(name="x", features=FEATURES)
    again = ExtensionInfo.model_validate(info.model_dump())
    assert again.features[2].not_for_owner and again.features[0].rights[1].name == "Add and change"
