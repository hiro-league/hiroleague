"""What an extension offers, typed, and the one form for a link to a page (offers.py)."""

import pytest
from pydantic import ValidationError

from hiro_channel_sdk import ExtensionInfo, MethodEntry, PageLink, SignInEntry, SiteEntry, TellsEntry

# Each entry as the apps on the build kit write it today (HomeHiro's extension.py, the kit's site entry).
HOME_KNOWS = {"method": "home.devices", "name": "Home's devices", "says": "The home's devices"}
HOME_SIGN_IN = {"kind": "sign_in", "id": "home_assistant", "label": "Home Assistant"}
SITE = {"kind": "site", "title": "Home", "icon": "house", "url": "http://homehiro.local", "roles": []}


def test_todays_descriptions_fit_their_types() -> None:
    info = ExtensionInfo.model_validate({
        "name": "home",
        "offers": {
            "knows": [HOME_KNOWS],
            "can_do": [HOME_SIGN_IN, {"method": "home.speak", "name": "Say it", "says": "On a camera speaker"}],
            "tells": [{"resource": "presence", "name": "Who is home"}],
            "shows": [SITE],
        },
    })
    assert isinstance(info.offers.knows[0], MethodEntry)
    assert isinstance(info.offers.can_do[0], SignInEntry)
    assert isinstance(info.offers.can_do[1], MethodEntry)
    assert isinstance(info.offers.tells[0], TellsEntry)
    assert isinstance(info.offers.shows[0], SiteEntry)
    # Stored and read back as plain JSON, as the core keeps it.
    dumped = info.model_dump(mode="json")["offers"]
    assert dumped["can_do"][0] == HOME_SIGN_IN
    assert dumped["shows"][0] == SITE


@pytest.mark.parametrize(
    ("slot", "entry"),
    [
        ("knows", {"name": "No method"}),  # a method entry without its method
        ("knows", {**HOME_KNOWS, "colour": "red"}),  # a field no type has
        ("can_do", {"kind": "sign_in", "label": "No id"}),
        ("tells", {"name": "No resource"}),
        ("shows", {**SITE, "kind": "page"}),  # a kind the slot doesn't know
    ],
)
def test_an_entry_that_fits_no_type_is_refused_naming_it(slot: str, entry: dict) -> None:
    with pytest.raises(ValidationError) as refused:
        ExtensionInfo.model_validate({"name": "home", "offers": {slot: [entry]}})
    assert f"offers.{slot}.0" in str(refused.value)


def test_a_link_names_an_app_or_the_admin_and_a_page() -> None:
    assert PageLink(app="home", path="/streams?cam=cam3").app == "home"
    assert PageLink(path="/people").app is None  # the core's admin


@pytest.mark.parametrize("path", ["streams", "//evil.example/x", "https://evil.example", "/\\evil"])
def test_a_link_never_leaves_its_site(path: str) -> None:
    with pytest.raises(ValidationError):
        PageLink(app="home", path=path)
