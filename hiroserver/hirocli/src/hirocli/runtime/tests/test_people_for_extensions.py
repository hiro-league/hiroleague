"""Phase 6: extensions read and change the family list, and are told when it changes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hirocli.domain.admin_sign_in import give_sign_in
from hirocli.domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from hirocli.domain.people import add_person
from hirocli.runtime.people_for_extensions import (
    handle_people_add,
    handle_people_list,
    handle_people_update,
    handle_roles_add,
    handle_roles_remove,
    watch_people_changes,
)
from hirocli.runtime.request_handler import RequestRefused


def _ctx(workspace: Path) -> SimpleNamespace:
    server_ctx = SimpleNamespace(workspace_path=workspace, extension_manager=None)
    return SimpleNamespace(server_ctx=server_ctx, msg=SimpleNamespace(routing=SimpleNamespace(sender_id="ext-home")))


def test_the_list_has_people_and_roles_without_sign_in_details(tmp_path: Path) -> None:
    michel = add_person(tmp_path, name="Michel", role_id="owner", whatsapp="201000000001")
    give_sign_in(tmp_path, michel.person_id, sign_in="michel", password="correct horse")
    answer = asyncio.run(handle_people_list({}, _ctx(tmp_path)))
    assert answer["people"] == [
        {"person_id": michel.person_id, "name": "Michel", "calls_them": "", "whatsapp": "201000000001", "role_id": "owner"}
    ]
    assert [r["role_id"] for r in answer["roles"]] == ["owner", "adult", "kid"]


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
        self.sent: list[tuple[str, str]] = []

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {"ext-1": {"name": "home"}}

    async def send_event(self, extension_id: str, event_type: str, data: dict[str, Any] | None = None) -> bool:
        self.sent.append((extension_id, event_type))
        return True


def test_every_connected_extension_is_told_of_a_change_in_its_workspace(tmp_path: Path) -> None:
    extensions = FakeExtensions()
    bus = get_domain_event_bus()

    async def run() -> None:
        bus.attach_loop(asyncio.get_running_loop())
        stop = watch_people_changes(extensions, tmp_path)
        try:
            add_person(tmp_path, name="Mona", role_id="adult")  # publishes people.changed
            bus.publish(DomainEvent(DomainEventType.PEOPLE_CHANGED, tmp_path / "other", {}))  # another workspace
            await asyncio.sleep(0.05)
        finally:
            stop()
            bus.detach_loop()

    asyncio.run(run())
    assert extensions.sent == [("ext-1", "people.changed")]
