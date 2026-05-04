"""Tests for ResourceChangeBroadcaster — debounce, fan-out, versioning."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hiro_channel_sdk.constants import EVENT_TYPE_RESOURCE_CHANGED
from hirocli.runtime.resource_change_broadcaster import ResourceChangeBroadcaster
from hirocli.runtime.resource_versioning import ResourceVersionStore


@pytest.mark.asyncio
async def test_no_connected_devices_no_emit(tmp_path: Path) -> None:
    emitted: list[object] = []

    async def emit(msg: object) -> None:
        emitted.append(msg)

    store = ResourceVersionStore()
    b = ResourceChangeBroadcaster(tmp_path, emit, version_store=store)
    b.start()
    try:
        b._on_channel_changed(tmp_path, 1)  # noqa: SLF001 — exercised as domain would
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
        b._on_channel_changed(tmp_path, 1)  # noqa: SLF001
        b._on_channel_changed(tmp_path, 2)
        b._on_channel_changed(tmp_path, 3)
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

        class _Prefs:
            pass

        b._on_preferences_saved(tmp_path, _Prefs())  # noqa: SLF001
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
        b._on_channel_changed(tmp_path, 1)  # noqa: SLF001
        await asyncio.sleep(0.15)
        v1 = emitted[-1].event.data["resource_sync_version"]
        emitted.clear()
        b._on_channel_changed(tmp_path, 2)  # noqa: SLF001
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
        b._on_channel_changed(tmp_path, 1)  # noqa: SLF001
        await asyncio.sleep(0.15)
        assert len(emitted) == 2
        assert sorted(r for r, _ in emitted) == ["d1", "d2"]
    finally:
        b.close()
