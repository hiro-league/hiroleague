"""Tests for ResourceChangeBroadcaster — debounce, fan-out, versioning, threads."""

from __future__ import annotations

import asyncio
import concurrent.futures
from pathlib import Path

import pytest
import pytest_asyncio

from hiro_channel_sdk.constants import EVENT_TYPE_RESOURCE_CHANGED
from hirocli.domain.events import (
    DomainEvent,
    DomainEventType,
    get_domain_event_bus,
)
from hirocli.runtime.resource_change_broadcaster import ResourceChangeBroadcaster
from hirocli.runtime.resource_versioning import ResourceVersionStore


@pytest_asyncio.fixture(autouse=True)
async def _bus_attached_to_loop():
    """Attach the singleton bus to the test's running loop and clean up after."""
    bus = get_domain_event_bus()
    bus.reset()
    bus.attach_loop(asyncio.get_running_loop())
    yield
    bus.reset()


def _channel_changed(workspace_path: Path, channel_id: int) -> DomainEvent:
    return DomainEvent(
        type=DomainEventType.CHANNEL_CHANGED,
        workspace_path=workspace_path,
        payload={"channel_id": channel_id},
    )


def _preferences_saved(workspace_path: Path) -> DomainEvent:
    return DomainEvent(
        type=DomainEventType.PREFERENCES_SAVED,
        workspace_path=workspace_path,
        payload={"prefs": object()},
    )


@pytest.mark.asyncio
async def test_no_connected_devices_no_emit(tmp_path: Path) -> None:
    emitted: list[object] = []

    async def emit(msg: object) -> None:
        emitted.append(msg)

    store = ResourceVersionStore()
    b = ResourceChangeBroadcaster(tmp_path, emit, version_store=store)
    b.start()
    try:
        get_domain_event_bus().publish(_channel_changed(tmp_path, 1))
        await asyncio.sleep(0.15)
        assert not emitted
        assert store.get("channels") == 0
    finally:
        b.close()


@pytest.mark.asyncio
async def test_debounce_single_emit_per_burst(tmp_path: Path) -> None:
    emitted: list[object] = []

    async def emit(msg: object) -> None:
        emitted.append(msg)

    store = ResourceVersionStore()
    b = ResourceChangeBroadcaster(tmp_path, emit, version_store=store)
    b.start()
    try:
        await b.handle_device_connected("dev_a")
        bus = get_domain_event_bus()
        bus.publish(_channel_changed(tmp_path, 1))
        bus.publish(_channel_changed(tmp_path, 2))
        bus.publish(_channel_changed(tmp_path, 3))
        await asyncio.sleep(0.15)
        assert len(emitted) == 1
        msg = emitted[0]
        assert msg.event.type == EVENT_TYPE_RESOURCE_CHANGED
        assert msg.event.data["resource"] == "channels"
        assert msg.event.data["resource_sync_version"] == 1
        assert store.get("channels") == 1
    finally:
        b.close()


@pytest.mark.asyncio
async def test_preferences_saved_maps_channels_and_policy(tmp_path: Path) -> None:
    emitted: list[object] = []

    async def emit(msg: object) -> None:
        emitted.append(msg)

    store = ResourceVersionStore()
    b = ResourceChangeBroadcaster(tmp_path, emit, version_store=store)
    b.start()
    try:
        await b.handle_device_connected("dev_a")

        get_domain_event_bus().publish(_preferences_saved(tmp_path))
        await asyncio.sleep(0.15)
        assert len(emitted) == 2
        resources = {m.event.data["resource"] for m in emitted}
        assert resources == {"channels", "policy"}
    finally:
        b.close()


@pytest.mark.asyncio
async def test_version_monotonic_per_resource(tmp_path: Path) -> None:
    emitted: list[object] = []

    async def emit(msg: object) -> None:
        emitted.append(msg)

    store = ResourceVersionStore()
    b = ResourceChangeBroadcaster(tmp_path, emit, version_store=store)
    b.start()
    try:
        await b.handle_device_connected("dev_a")
        bus = get_domain_event_bus()
        bus.publish(_channel_changed(tmp_path, 1))
        await asyncio.sleep(0.15)
        v1 = emitted[-1].event.data["resource_sync_version"]
        emitted.clear()
        bus.publish(_channel_changed(tmp_path, 2))
        await asyncio.sleep(0.15)
        v2 = emitted[-1].event.data["resource_sync_version"]
        assert v2 == v1 + 1
    finally:
        b.close()


@pytest.mark.asyncio
async def test_two_devices_each_get_one_envelope(tmp_path: Path) -> None:
    emitted: list[tuple[str, object]] = []

    async def emit(msg: object) -> None:
        emitted.append((msg.routing.recipient_id, msg))

    store = ResourceVersionStore()
    b = ResourceChangeBroadcaster(tmp_path, emit, version_store=store)
    b.start()
    try:
        await b.handle_device_connected("d1")
        await b.handle_device_connected("d2")
        get_domain_event_bus().publish(_channel_changed(tmp_path, 1))
        await asyncio.sleep(0.15)
        assert len(emitted) == 2
        assert sorted(r for r, _ in emitted) == ["d1", "d2"]
    finally:
        b.close()


@pytest.mark.asyncio
async def test_publish_from_worker_thread_delivers(tmp_path: Path) -> None:
    """Regression: admin endpoints run domain mutations in a worker thread.

    The bus must trampoline the publish back onto the runtime loop so the
    broadcaster's async subscriber actually fires.
    """
    emitted: list[object] = []

    async def emit(msg: object) -> None:
        emitted.append(msg)

    store = ResourceVersionStore()
    b = ResourceChangeBroadcaster(tmp_path, emit, version_store=store)
    b.start()
    try:
        await b.handle_device_connected("dev_a")
        bus = get_domain_event_bus()

        def _publish_in_thread() -> None:
            # No running loop in this thread — exactly the admin worker case.
            bus.publish(
                DomainEvent(
                    type=DomainEventType.CHARACTER_PHOTO_CHANGED,
                    workspace_path=tmp_path,
                    payload={"character_id": "hiro"},
                )
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            await asyncio.get_running_loop().run_in_executor(pool, _publish_in_thread)

        await asyncio.sleep(0.2)
        assert len(emitted) == 1
        assert emitted[0].event.data["resource"] == "characters"
        assert emitted[0].event.data["reason"] == "character_photo_changed"
    finally:
        b.close()


@pytest.mark.asyncio
async def test_publish_with_no_loop_attached_drops(tmp_path: Path) -> None:
    """If the bus has no loop (pre-startup / post-shutdown), publishes warn and drop."""
    emitted: list[object] = []

    async def emit(msg: object) -> None:
        emitted.append(msg)

    bus = get_domain_event_bus()
    bus.detach_loop()

    store = ResourceVersionStore()
    b = ResourceChangeBroadcaster(tmp_path, emit, version_store=store)
    b.start()
    try:
        await b.handle_device_connected("dev_a")
        bus.publish(_channel_changed(tmp_path, 1))
        await asyncio.sleep(0.15)
        assert emitted == []
    finally:
        b.close()
