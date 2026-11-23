"""The shared foundation between the core and its extensions (unified communication, phase 3): an extension's
``resource.changed`` reaches the core's bus, a description with an offer that fits no type is refused at sign-in, and a
link to a page turns into the right address. The manager and an app's client run for real, on 127.0.0.1."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from hiro_channel_sdk import PageLink
from hiro_channel_sdk.constants import EVENT_TYPE_RESOURCE_CHANGED
from hiro_channel_sdk.extension import (
    STATUS_CONNECTED,
    ExtensionClient,
    ExtensionCredentials,
    ExtensionInfo,
)

from hirocli.domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from hirocli.domain.extensions import list_paired_extensions, start_extension_pairing
from hirocli.runtime.page_links import address
from hirocli.runtime.resource_changes_from_extensions import ResourceChangesFromExtensions, change_from
from hirocli.runtime.sign_in_for_extensions import Site
from hirocli.runtime.tests.test_extension_manager_channels import _core, _free_port, _wait_for

HOME_INFO = {
    "name": "home",
    "offers": {"tells": [{"resource": "presence", "name": "Who is home", "says": "Someone came or left"}]},
}


def test_a_change_is_passed_on_only_for_a_declared_resource() -> None:
    assert change_from(HOME_INFO, {"resource": "presence", "ids": ["cp1", 2]}) == ("presence", ["cp1", "2"])
    assert change_from(HOME_INFO, {"resource": "presence"}) == ("presence", [])
    assert change_from(HOME_INFO, {"resource": "cameras"}) == "'cameras' isn't in its offers.tells"
    assert change_from(HOME_INFO, {}) == "it names no resource"
    assert change_from(HOME_INFO, {"resource": "presence", "ids": "cp1"}) == "its ids aren't a list"


def test_an_apps_change_reaches_the_cores_bus_with_its_name(tmp_path: Path, caplog) -> None:
    caplog.set_level("INFO", logger="EXTENSIONS")

    async def scenario() -> None:
        workspace = tmp_path / "ws"
        port = _free_port()
        manager, _chat = _core(workspace, port)
        ResourceChangesFromExtensions(manager._ctx, manager).register()
        bus = get_domain_event_bus()
        bus.attach_loop(asyncio.get_running_loop())
        heard: list[DomainEvent] = []

        async def on_change(event: DomainEvent) -> None:
            heard.append(event)

        bus.subscribe(DomainEventType.EXTENSION_RESOURCE_CHANGED, on_change)
        server = asyncio.create_task(manager.run())
        try:
            await _wait_for(lambda: manager.listen_state()["listening"])
            code = start_extension_pairing(workspace, code_length=6, ttl_seconds=60).code
            info = ExtensionInfo.model_validate(HOME_INFO)
            client = ExtensionClient(f"ws://127.0.0.1:{port}", info, ExtensionCredentials(tmp_path / "home"))
            client.pair(code)
            running = asyncio.create_task(client.run())
            await _wait_for(lambda: client.status == STATUS_CONNECTED)

            assert await client.send_event(EVENT_TYPE_RESOURCE_CHANGED, {"resource": "presence", "ids": ["cp1"]})
            await _wait_for(lambda: len(heard) == 1)
            assert heard[0].payload == {"extension": "home", "resource": "presence", "ids": ["cp1"]}

            # A resource it never declared: dropped, with one warning that names the app and why
            assert await client.send_event(EVENT_TYPE_RESOURCE_CHANGED, {"resource": "cameras"})
            await _wait_for(lambda: any("change dropped" in r.getMessage() for r in caplog.records))
            await asyncio.sleep(0.1)
            assert len(heard) == 1
            [dropped] = [r for r in caplog.records if "change dropped" in r.getMessage()]
            assert dropped.levelname == "WARNING" and "home" in dropped.getMessage()
            assert "'cameras' isn't in its offers.tells" in dropped.getMessage()

            await client.stop()
            await asyncio.wait_for(running, 5)
        finally:
            bus.unsubscribe(DomainEventType.EXTENSION_RESOURCE_CHANGED, on_change)
            bus.detach_loop()
            manager._ctx.stop_event.set()
            await asyncio.wait_for(server, 5)

    asyncio.run(scenario())


# The description is built unchecked on purpose, so pydantic warns when the client sends it.
@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
def test_an_offer_that_fits_no_type_is_refused_at_sign_in(tmp_path: Path, caplog) -> None:
    caplog.set_level("INFO", logger="EXTENSIONS")

    async def scenario() -> None:
        workspace = tmp_path / "ws"
        port = _free_port()
        manager, _chat = _core(workspace, port)
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])
        code = start_extension_pairing(workspace, code_length=6, ttl_seconds=60).code
        # Built without the SDK's own check, as an app on another SDK might send it: a "knows" entry with no method
        info = ExtensionInfo.model_construct(name="odd", version="0.0.1", offers={"knows": [{"name": "No method"}]})
        client = ExtensionClient(f"ws://127.0.0.1:{port}", info, ExtensionCredentials(tmp_path / "odd"))
        client.pair(code)
        running = asyncio.create_task(client.run())
        await _wait_for(lambda: any("Extension refused" in r.getMessage() for r in caplog.records))
        [refused] = [r for r in caplog.records if "Extension refused" in r.getMessage()]
        assert refused.levelname == "WARNING"
        assert "offers.knows.0.method" in str(getattr(refused, "attributes", None) or refused.__dict__)
        assert list_paired_extensions(workspace) == []
        await client.stop()
        await asyncio.wait_for(running, 5)
        manager._ctx.stop_event.set()
        await asyncio.wait_for(server, 5)

    asyncio.run(scenario())


SITES = [Site(extension_id="e1", extension="home", title="Home", icon="house", url="http://homehiro.local", roles=(),
              online=True)]


@pytest.mark.parametrize(
    ("link", "admin", "opens"),
    [
        (PageLink(app="home", path="/streams?cam=cam3"), "http://hiro.local", "http://homehiro.local/streams?cam=cam3"),
        (PageLink(path="/people"), "http://hiro.local/", "http://hiro.local/people"),  # the core's admin
        (PageLink(path="/people"), "", "/people"),  # shown inside the admin itself
        (PageLink(app="net", path="/status"), "http://hiro.local", None),  # an app with no site the core knows
    ],
)
def test_a_link_turns_into_the_address_of_its_page(link: PageLink, admin: str, opens: Any) -> None:
    assert address(link, SITES, admin) == opens
