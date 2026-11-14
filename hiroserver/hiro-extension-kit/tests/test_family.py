"""HiroLeague's family list in an app (family.py): the copy and its sync, roles and their rights from the family list,
the one-time copy of each role's rights from the app a feature came from (`Extension.rights_from`), and WhatsApp
numbers. The core is faked at its request (`fake_core`), so nothing leaves the PC.

Shared-code plan, step 1: NetHiro's and TrainHiro's tests each had this file; it is tested once, here."""

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from hiro_channel_sdk import ExtensionRequestError
from sqlmodel import Session, select

from hiro_extension_kit import settings
from hiro_extension_kit import family
from hiro_extension_kit.db import engine
from hiro_extension_kit.errors import Invalid, Unavailable
from hiro_extension_kit.auth.models import AppUser, CorePerson, Role

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


def _user(uid: str, name: str, role_id: str | None) -> None:
    with Session(engine) as s:
        s.merge(AppUser(id=uid, name=name, role_id=role_id, first_seen=NOW, last_seen=NOW))
        s.commit()


def test_the_sync_copies_people_and_roles_with_the_rights_the_core_grants(fake_core):
    fake_core.person("Youssef", "kid", "201000000002", "Yoyo")
    fake_core.roles.append({"role_id": "nanny", "name": "Nanny", "built_in": False})
    fake_core.roles[2].update(name="Child", rights=["status.see"], says="The kids")  # kid renamed in the core
    said = run(family.sync())
    assert "1 added" in said and "role Nanny added" in said
    with Session(engine) as s:
        assert [(p.name, p.calls_them, p.whatsapp, p.role_id) for p in s.exec(select(CorePerson))] == [
            ("Youssef", "Yoyo", "201000000002", "kid")]
        kid = s.get(Role, "kid")
        assert kid is not None and (kid.name, kid.core, kid.rights, kid.says) == ("Child", True, ["status.see"], "The kids")
    assert run(family.sync()) == []  # nothing changed: nothing said, no notice
    fake_core.roles[2]["rights"] = ["status.see", "status.alerts"]
    assert run(family.sync()) == ["what Child may do changed"]
    fake_core.roles = [r for r in fake_core.roles if r["role_id"] != "nanny"]
    fake_core.people.clear()
    assert set(run(family.sync())) == {"role Nanny removed", "Youssef left the family list"}


def test_each_roles_rights_are_copied_from_the_app_named_once(fake_core):
    """The first sync asks the core to copy each role's rights from `rights_from` (`home`), once (Phase 9b, 9c)."""
    run(family.sync())
    run(family.sync())
    copies = [p for m, p in fake_core.asked if m == "roles.import_rights"]
    assert copies == [{"copy_from": "home"}]
    with Session(engine) as s:
        assert settings.get(s, family.RIGHTS_COPIED) is not None


def test_a_core_that_cant_copy_the_rights_yet_is_asked_again(fake_core):
    fake_core.answers["roles.import_rights"] = ExtensionRequestError("internal_error", "unknown method")
    run(family.sync())  # the list is still read
    with Session(engine) as s:
        assert settings.get(s, family.RIGHTS_COPIED) is None
    del fake_core.answers["roles.import_rights"]
    run(family.sync())
    assert [m for m, _ in fake_core.asked].count("roles.import_rights") == 2


def test_two_roles_swapping_names_in_the_core_dont_trip_the_unique_name(fake_core):
    run(family.sync())
    fake_core.roles[1]["name"], fake_core.roles[2]["name"] = "Kid", "Adult"
    run(family.sync())
    with Session(engine) as s:
        assert (s.get(Role, "adult").name, s.get(Role, "kid").name) == ("Kid", "Adult")  # type: ignore[union-attr]


def test_with_the_core_down_the_copy_stays(fake_core):
    fake_core.person("Mark", "kid")
    run(family.sync())
    fake_core.connected = False
    with pytest.raises(Unavailable, match="isn't connected to HiroLeague"):
        run(family.sync())
    with Session(engine) as s:
        assert [p.name for p in s.exec(select(CorePerson))] == ["Mark"]  # nobody is locked out


@pytest.mark.parametrize(("answer", "kind", "says"), [
    ({"people": [{"name": "no id"}], "roles": []}, family.FamilyError, "HiroLeague's answer about a person can't be read"),
    ({"roles": []}, family.FamilyError, "HiroLeague's family list can't be read"),
    (ExtensionRequestError("timeout", "no answer"), family.FamilyError, "HiroLeague didn't answer in 15 s (people.list)"),
    (ExtensionRequestError("internal_error", "boom"), family.FamilyError, "HiroLeague failed (internal_error): boom"),
    (ExtensionRequestError("not_connected", "closed"), Unavailable, "isn't connected to HiroLeague"),
])
def test_the_cores_failures_in_words(fake_core, answer, kind, says):
    fake_core.answers["people.list"] = answer
    with pytest.raises(kind, match=says.replace("(", r"\(").replace(")", r"\)")):
        run(family.sync())


def test_a_failed_round_is_logged_and_the_worker_goes_on(fake_core, monkeypatch, caplog):
    monkeypatch.setattr(family, "EVERY", 0.01)
    fake_core.answers["people.list"] = ExtensionRequestError("internal_error", "boom")
    worker = family.FamilySync()

    async def scenario():
        worker.start()
        await asyncio.sleep(0.1)
        del fake_core.answers["people.list"]
        fake_core.person("Mona")
        await asyncio.sleep(0.1)
        await worker.stop()

    with caplog.at_level(logging.WARNING, "testapp.family"):
        run(scenario())
    assert any("Family: reading HiroLeague's family list" in r.getMessage() and "boom" in r.getMessage() for r in caplog.records)
    with Session(engine) as s:
        assert [p.name for p in s.exec(select(CorePerson))] == ["Mona"]  # a later round worked


def test_the_cores_people_changed_and_a_connect_start_a_sync(fake_core, monkeypatch):
    from hiro_extension_kit.events import bus
    from hiro_extension_kit.hiroleague import CONNECTED

    monkeypatch.setattr(family, "EVERY", 60)
    handlers = fake_core.handlers
    worker = family.FamilySync()

    def reads() -> int:
        return [m for m, _ in fake_core.asked].count("people.list")

    async def until(count: int) -> int:
        # Wait for that many reads (at most 5 s), not a fixed sleep: a round reads the database and asks the (fake) core,
        # and on 2026-11-12 NetHiro's nightly check (tests 12 at a time on a busy server) missed a 50 ms window twice
        for _ in range(500):
            if reads() >= count:
                break
            await asyncio.sleep(0.01)
        return reads()

    async def scenario():
        worker.start()
        await asyncio.sleep(0.05)  # no round on start: only the timer (60 s here), the event or a connect starts one
        first = reads()
        await handlers["people.changed"]("people.changed", {})
        after_event = await until(first + 1)
        bus.publish(CONNECTED)
        after_connect = await until(after_event + 1)
        await asyncio.sleep(0.05)  # nothing more comes
        await worker.stop()
        return first, after_event, after_connect, reads()

    first, after_event, after_connect, last = run(scenario())
    assert after_event == first + 1 and after_connect == after_event + 1 and last == after_connect


def test_users_roles_follow_their_core_persons(fake_core):
    mark = fake_core.person("Mark", "kid")
    run(family.sync())
    _user(mark["person_id"], "Mark", None)
    _user("cp-gone", "Gone", "adult")  # no longer in the family list
    with Session(engine) as s:
        family.recompute_roles(s)
        s.commit()
        assert s.get(AppUser, mark["person_id"]).role_id == "kid"  # type: ignore[union-attr]
        assert s.get(AppUser, "cp-gone").role_id is None  # type: ignore[union-attr]  # waits
    mark["role_id"] = "adult"
    run(family.sync())
    with Session(engine) as s:
        assert s.get(AppUser, mark["person_id"]).role_id == "adult"  # type: ignore[union-attr]


def test_a_whatsapp_alert_reaches_a_core_person_with_a_number(fake_core):
    mona, mark = fake_core.person("Mona", "adult", "201000000001"), fake_core.person("Mark", "kid")
    run(family.sync())
    with Session(engine) as s:
        assert family.reachable(s, mona["person_id"]).whatsapp == "201000000001"
        with pytest.raises(Invalid, match="Mark has no WhatsApp number"):
            family.reachable(s, mark["person_id"])
        with pytest.raises(Invalid, match="isn't in HiroLeague's family list"):
            family.reachable(s, "hh-person")
