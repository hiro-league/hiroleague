"""The key rule (domain/extension_keys.py) and the records' check at pairing (one key, one dashed form)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.domain.extension_keys import HIRO_LEAGUE_OWN, key_refusal, same_dashed
from hirocli.domain.extensions import ExtensionNameTaken, add_paired_extension, check_name_free


@pytest.mark.parametrize("key", sorted(HIRO_LEAGUE_OWN) + ["acme.weather", "example.hello", "h1.app"])
def test_hiro_leagues_own_and_publisher_keys_pass(key: str) -> None:
    assert key_refusal(key) is None


def test_every_live_name_passes() -> None:
    # Simone's records on Nov 25, 2026: a rule that refused one would lock that app out at its next pairing
    for name in ("home", "net", "train", "study", "reports", "eval", "whatsapp", "devices"):
        assert key_refusal(name) is None, name


@pytest.mark.parametrize(
    ("key", "words"),
    [
        ("weather", "no publisher"),
        ("hiroleague", "HiroLeague's own"),
        ("hiro.weather", "reserved"),
        ("hiroleague.weather", "reserved"),
        ("hirofan.weather", "reserved"),
        ("Acme.Weather", "isn't name or publisher.name"),
    ],
)
def test_the_rule_refuses_in_words(key: str, words: str) -> None:
    refusal = key_refusal(key)
    assert refusal and words in refusal


def test_two_keys_with_one_dashed_form() -> None:
    assert same_dashed("acme.weather", "acme-weather.x") is False
    assert same_dashed("a-b.c", "a.b-c") is True
    assert same_dashed("acme.weather", "acme.weather") is False


def test_pairing_refuses_a_key_the_rule_refuses(tmp_path: Path) -> None:
    with pytest.raises(ExtensionNameTaken, match="no publisher"):
        add_paired_extension(tmp_path, name="weather", public_key="k", info={})


def test_pairing_refuses_the_dashed_form_of_a_paired_key(tmp_path: Path) -> None:
    add_paired_extension(tmp_path, name="a-b.c", public_key="k1", info={})
    with pytest.raises(ExtensionNameTaken, match="would share its service"):
        check_name_free(tmp_path, "a.b-c")
    check_name_free(tmp_path, "a.b-d")  # another dashed form is free
