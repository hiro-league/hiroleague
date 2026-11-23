"""The shared foundation an app uses with the core (unified communication, phase 3): telling the core something it
keeps changed (hiroleague.tell_changed), its offers as typed entries (hiroleague.info_for), and the person an ask is
for (asked_for.py). The core is faked (testing.FakeCore): nothing leaves the PC."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from hiro_extension_kit import hiroleague, testing
from hiro_extension_kit.asked_for import AskedFor, asked_for
from hiro_extension_kit.auth.models import AppUser, CorePerson, Role
from hiro_extension_kit.db import engine

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def core(monkeypatch):
    fake = testing.FakeCore()
    monkeypatch.setattr(hiroleague, "link", testing.FakeLink(fake))
    return fake


def test_a_change_the_app_declared_is_told_to_the_core(core):
    assert run(hiroleague.tell_changed("checks", ["disk"])) is True
    assert core.events == [("resource.changed", {"resource": "checks", "ids": ["disk"]})]
    assert run(hiroleague.tell_changed("checks")) is True
    assert core.events[-1] == ("resource.changed", {"resource": "checks"})


def test_a_change_the_app_never_declared_is_its_own_mistake(core):
    with pytest.raises(ValueError, match="Extension.tells"):
        run(hiroleague.tell_changed("people"))
    assert core.events == []


def test_with_the_core_away_the_change_is_not_sent(core):
    core.connected = False
    assert run(hiroleague.tell_changed("checks")) is False


def test_the_app_declares_what_it_tells_as_typed_entries():
    offers = hiroleague.info_for("http://test.hiro.local").offers
    assert [t.resource for t in offers.tells] == ["checks"]
    assert offers.shows[0].url == "http://test.hiro.local"


def _family(person_id: str, role_id: str, rights: list[str], *, denied: bool = False) -> None:
    with Session(engine) as s:
        s.merge(Role(id=role_id, name=role_id.title(), rights=rights, created_at=NOW, updated_at=NOW))
        s.merge(CorePerson(id=person_id, name=person_id, role_id=role_id, synced_at=NOW))
        if denied:
            s.merge(AppUser(id=person_id, name=person_id, role_id=role_id, denied=True, first_seen=NOW, last_seen=NOW))
        s.commit()


def test_the_core_asking_for_itself_names_nobody():
    assert run(asked_for({"_asked_by": "home"})) is None


def test_an_ask_for_a_kid_gets_the_kids_rights():
    _family("cp-kid", "kid", ["logs.see"])
    who = run(asked_for({"_for_person": "cp-kid"}))
    assert who == AskedFor("cp-kid", "kid", ("logs.see",))
    assert who.can("logs") and not who.can("status") and not who.can("status", "alerts")


def test_the_owner_may_do_everything():
    _family("cp-owner", "owner", [])
    who = run(asked_for({"_for_person": "cp-owner"}))
    assert who is not None and who.can("status", "alerts") and who.can("settings")


@pytest.mark.parametrize("person", ["cp-stranger", "cp-denied"])
def test_someone_the_app_doesnt_know_or_shut_out_has_no_rights(person):
    _family("cp-denied", "adult", ["status.see", "logs.see"], denied=True)
    who = run(asked_for({"_for_person": person}))
    assert who == AskedFor(person) and not who.can("status") and not who.can("logs")
