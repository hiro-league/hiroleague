"""Phase 6: extensions read and change the family list, and are told when it changes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hirocli.domain.admin_sign_in import give_sign_in
from hirocli.domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from hirocli.domain.extensions import add_paired_extension
from hirocli.domain.people import add_person
from hirocli.runtime.people_for_extensions import (
    handle_people_add,
    handle_people_list,
    handle_people_update,
    handle_roles_add,
    handle_roles_remove,
)
from hirocli.runtime.request_handler import RequestRefused


def _ctx(workspace: Path) -> SimpleNamespace:
    # Phase 9a: people.list answers in the calling extension's terms, so the caller is a paired extension.
    home = add_paired_extension(workspace, name="home", public_key="k", info={"name": "home"})
    server_ctx = SimpleNamespace(workspace_path=workspace, extension_manager=None)
    return SimpleNamespace(
        server_ctx=server_ctx,
        workspace_path=workspace,
        msg=SimpleNamespace(routing=SimpleNamespace(sender_id=home.extension_id)),
    )


def test_the_list_has_people_and_roles_without_sign_in_details(tmp_path: Path) -> None:
    michel = add_person(tmp_path, name="Michel", role_id="owner", whatsapp="201000000001")
    give_sign_in(tmp_path, michel.person_id, sign_in="michel", password="correct horse")
    answer = asyncio.run(handle_people_list({}, _ctx(tmp_path)))
    assert answer["people"] == [
        {"person_id": michel.person_id, "name": "Michel", "calls_them": "", "whatsapp": "201000000001", "role_id": "owner",
         "role_ids": ["owner"]}
    ]
    assert [r["role_id"] for r in answer["roles"]] == ["owner", "adult", "kid"]


def test_the_list_carries_every_role_and_the_first(tmp_path: Path) -> None:
    """Permissions phase 1: role_ids is every role held; role_id stays the first, what an app knowing one reads."""
    add_person(tmp_path, name="Mark", role_ids=["kid", "adult"])
    person = asyncio.run(handle_people_list({}, _ctx(tmp_path)))["people"][0]
    assert person["role_ids"] == ["adult", "kid"] and person["role_id"] == "adult"


def test_an_extension_sets_several_roles_or_one(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    added = asyncio.run(handle_people_add({"name": "Mark", "role_ids": ["kid", "adult"]}, ctx))["person"]
    assert added["role_ids"] == ["adult", "kid"]
    kept = asyncio.run(handle_people_update({"person_id": added["person_id"], "role_id": "adult"}, ctx))["person"]
    assert kept["role_ids"] == ["adult", "kid"]  # already their first role: nothing changes
    with pytest.raises(RequestRefused, match="list"):
        asyncio.run(handle_people_update({"person_id": added["person_id"], "role_ids": "kid"}, ctx))


def test_an_extension_adds_and_changes_people_and_roles(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    added = asyncio.run(handle_people_add({"name": "Grandma", "role_id": "adult"}, ctx))["person"]
    changed = asyncio.run(
        handle_people_update({"person_id": added["person_id"], "whatsapp": "+20 100 000 0009"}, ctx)
    )["person"]
    assert changed["whatsapp"] == "201000000009" and changed["name"] == "Grandma"
    assert asyncio.run(handle_roles_add({"name": "Guest"}, ctx))["role"]["role_id"] == "guest"
    assert asyncio.run(handle_roles_remove({"role_id": "guest"}, ctx)) == {}


def test_a_refused_change_says_why(tmp_path: Path) -> None:
    with pytest.raises(RequestRefused) as refused:
        asyncio.run(handle_people_add({"name": "Grandma", "role_id": "guest"}, _ctx(tmp_path)))
    assert refused.value.code == "invalid_params" and "no role" in refused.value.message
    with pytest.raises(RequestRefused):
        asyncio.run(handle_roles_remove({"role_id": "owner"}, _ctx(tmp_path)))


class FakeExtensions:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict[str, Any]]] = []

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {"ext-1": {"name": "home"}}

    async def send_event(self, extension_id: str, event_type: str, data: dict[str, Any] | None = None) -> bool:
        self.sent.append((extension_id, event_type, dict(data or {})))
        return True


def test_every_connected_app_is_told_of_a_change_in_its_workspace(tmp_path: Path) -> None:
    """Unified communication, phase 4: the one sender's resource.changed for people, to the apps."""
    from hirocli.runtime.resource_change_broadcaster import ResourceChangeBroadcaster
    from hirocli.runtime.resource_versioning import ResourceVersionStore

    extensions = FakeExtensions()
    bus = get_domain_event_bus()

    async def to_phones(_msg: object) -> None:
        raise AssertionError("the family is the apps' copy, never the phones'")

    async def run() -> None:
        bus.attach_loop(asyncio.get_running_loop())
        sender = ResourceChangeBroadcaster(tmp_path, to_phones, version_store=ResourceVersionStore())
        sender.set_extension_manager(extensions)  # type: ignore[arg-type]
        sender.start()
        try:
            add_person(tmp_path, name="Mona", role_id="adult")  # publishes the family's change
            bus.publish(DomainEvent(DomainEventType.PEOPLE_CHANGED, tmp_path / "other", {}))  # another workspace
            await asyncio.sleep(0.3)
        finally:
            sender.close()
            bus.detach_loop()

    asyncio.run(run())
    assert extensions.sent == [
        ("ext-1", "resource.changed", {"resource": "people", "reason": "people_changed", "resource_sync_version": 1})]
