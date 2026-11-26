"""The package manifest (hiro-extension.toml) and the key's grammar."""

from __future__ import annotations

import pytest

from hiro_channel_sdk.manifest import (
    Manifest,
    ManifestError,
    dashed,
    key_problem,
    parse_manifest,
    publisher,
    render_manifest,
)

GOOD = """
key = "acme.weather"
kind = "app"
title = "Weather"
version = "0.1.0"
core = ">=0.2, <0.4"
command = "acme-weather"
port = 8170
predeploy = "python -m acme_weather.predeploy"
"""


@pytest.mark.parametrize("key", ["home", "acme.weather", "a1-b.c-2", "x", "a" * 13 + "." + "b" * 13])
def test_a_key_is_name_or_publisher_dot_name(key: str) -> None:
    assert key_problem(key) is None


@pytest.mark.parametrize("key", ["", "Home", "1home", "-home", "home-", "acme-.weather", "acme.", ".weather", "a.b.c", "acme_weather", "a" * 28])
def test_a_key_outside_the_grammar_is_said_in_words(key: str) -> None:
    assert key_problem(key)


def test_the_dashed_form_and_the_publisher() -> None:
    assert dashed("acme.weather") == "acme-weather"
    assert dashed("home") == "home"
    assert publisher("acme.weather") == "acme"
    assert publisher("home") is None


def test_a_manifest_reads_and_writes_back_the_same() -> None:
    manifest = parse_manifest(GOOD)
    assert manifest.key == "acme.weather"
    assert manifest.core == ">=0.2,<0.4"
    assert manifest.health == "/api/health"
    assert parse_manifest(render_manifest(manifest)) == manifest


def test_an_app_names_its_port_and_a_channel_none() -> None:
    with pytest.raises(ManifestError, match="port"):
        parse_manifest(GOOD.replace("port = 8170\n", ""))
    channel = Manifest(key="acme.chat", kind="channel", title="Chat", version="1.0.0", core=">=0.2", command="acme-chat")
    assert channel.port is None
    with pytest.raises(ValueError, match="no port"):
        Manifest(key="acme.chat", kind="channel", title="Chat", version="1.0.0", core=">=0.2", command="c", port=8000)


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (('key = "acme.weather"', 'key = "Acme"'), "key"),
        (('core = ">=0.2, <0.4"', 'core = "soon"'), "core versions"),
        (('version = "0.1.0"', 'version = "latest"'), "version"),
        (("port = 8170", "port = 80"), "between 1024"),
        (('title = "Weather"', 'title = "  "'), "title"),
        (('kind = "app"', 'kind = "plugin"'), "kind"),
    ],
)
def test_a_bad_field_is_refused_with_words(change: tuple[str, str], words: str) -> None:
    with pytest.raises(ManifestError, match=words):
        parse_manifest(GOOD.replace(*change))


def test_an_unknown_field_or_bad_toml_is_refused() -> None:
    with pytest.raises(ManifestError, match="colour isn't a field of the manifest"):
        parse_manifest(GOOD + 'colour = "blue"\n')
    with pytest.raises(ManifestError, match="isn't valid TOML"):
        parse_manifest("key = ")


def test_the_asks_and_the_address_ride_the_manifest_and_read_back_the_same() -> None:
    from hiro_channel_sdk.approvals import APPS_ASK, PEOPLE_NOTIFY, PEOPLE_SEE, AppAsk

    asks = (
        AppAsk(permission=PEOPLE_SEE, why="It greets people by name"),
        AppAsk(permission=PEOPLE_NOTIFY, required=False, why='Says "hello" on WhatsApp'),
        AppAsk(permission=APPS_ASK, to="home", why="Asks HomeHiro who is in"),
    )
    manifest = parse_manifest(GOOD).model_copy(update={"asks": asks, "site": "http://weather.local"})
    text = render_manifest(manifest)
    assert text.count("[[asks]]") == 3 and "required = false" in text
    assert parse_manifest(text) == manifest
    assert parse_manifest(GOOD).asks == ()
    with pytest.raises(ManifestError, match="site"):
        parse_manifest(GOOD + 'site = "weather.local"\n')
