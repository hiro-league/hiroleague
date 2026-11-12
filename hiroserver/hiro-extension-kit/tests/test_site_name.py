"""The app's LAN name (site_name.py): the label rules and reading a name back from an address. Pure. Claiming the name
through the core is each app's test (it runs the app's link with its Extension)."""

import pytest

from hiro_extension_kit.site_name import BadLabel, SiteName, name_of, site_name


def test_a_label_becomes_a_subdomain_or_a_one_word_local_name():
    assert site_name("home", "subdomain") == SiteName("home", "subdomain")
    assert site_name("home", "subdomain").name == "home.hiro.local"
    assert site_name(" Abc ", "local").name == "abc.local"  # trimmed, lower case
    assert site_name("abc", "local").url == "http://abc.local"
    assert site_name("home.hiro.local", "subdomain").label == "home"  # the whole name pasted
    assert site_name("my-home2.local", "local").label == "my-home2"


@pytest.mark.parametrize("label,kind", [
    ("", "subdomain"), ("  ", "local"), ("a.b", "local"), ("-home", "subdomain"), ("home-", "local"),
    ("ho me", "local"), ("hømé", "local"), ("x" * 64, "local"), ("home.hiro.local", "local"), ("home", "web"),
])
def test_labels_that_cant_be_a_name(label, kind):
    with pytest.raises(BadLabel):
        site_name(label, kind)


def test_an_empty_label_names_the_app():
    with pytest.raises(BadLabel, match=r"Type a name for TestApp \(e\.g\. home\)\."):
        site_name("", "subdomain")


def test_the_form_reads_the_label_and_kind_back_from_the_address():
    assert name_of("http://home.hiro.local") == SiteName("home", "subdomain")
    assert name_of("http://nethiro.local") == SiteName("nethiro", "local")  # the default, hand-written on the server
    for other in ("https://home.hiro.local", "http://nethiro.local:8130", "http://192.168.1.10", "http://a.b.local",
                  "http://home.hiro.local/app", ""):
        assert name_of(other) is None, other
