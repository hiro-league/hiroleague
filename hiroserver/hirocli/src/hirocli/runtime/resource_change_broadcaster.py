"""Emits ``resource.changed`` hints on workspace-domain mutations — Tier 1 substrate."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hiro_commons.log import Logger

from ..domain.character import subscribe_character_changes, unsubscribe_character_changes
from ..domain.conversation_channel import (
    subscribe_channel_changes,
    unsubscribe_channel_changes,
)
from ..domain.preferences import (
    WorkspacePreferences,
    subscribe_preferences_saved,
    unsubscribe_preferences_saved,
)
from .device_targeting import DeviceTargeting
from .envelope_factory import EnvelopeFactory
from .resource_registry import ResourceRegistry
from .resource_versioning import ResourceVersionStore

EmitOutbound = Callable[..., Awaitable[None]]

log = Logger.get("RESOURCE.CHANGED")


class ResourceChangeBroadcaster:
    """Debounced publisher for ``resource.changed`` envelopes."""

    DEBOUNCE_SECONDS: float = 0.1

    def __init__(
        self,
        workspace_path: Path,
        emit_outbound: EmitOutbound,
        *,
        version_store: ResourceVersionStore,
        registry: ResourceRegistry | None = None,
        targeting: DeviceTargeting | None = None,
    ) -> None:
        self._workspace_path = workspace_path
        self._emit_outbound = emit_outbound
        self._version_store = version_store
        self._registry = registry or ResourceRegistry()
        self._targeting = targeting or DeviceTargeting()
        self._connected_device_ids: set[str] = set()
        self._debounce_tasks: dict[str, asyncio.Task[None]] = {}

    def start(self) -> None:
        subscribe_preferences_saved(self._on_preferences_saved)
        subscribe_character_changes(self._on_character_changed)
        subscribe_channel_changes(self._on_channel_changed)

    def close(self) -> None:
        for task in list(self._debounce_tasks.values()):
            if not task.done():
                task.cancel()
        self._debounce_tasks.clear()
        unsubscribe_preferences_saved(self._on_preferences_saved)
        unsubscribe_character_changes(self._on_character_changed)
        unsubscribe_channel_changes(self._on_channel_changed)

    async def handle_device_connected(self, device_id: str) -> None:
        self._connected_device_ids.add(device_id)

    async def handle_device_disconnected(self, device_id: str) -> None:
        self._connected_device_ids.discard(device_id)

    async def clear_connected_devices(self) -> None:
        self._connected_device_ids.clear()

    def _on_preferences_saved(self, workspace_path: Path, prefs: WorkspacePreferences) -> None:
        del prefs
        if workspace_path != self._workspace_path:
            return
        self._schedule_for_signal("preferences_saved")

    def _on_character_changed(self, workspace_path: Path, character_id: str) -> None:
        del character_id
        if workspace_path != self._workspace_path:
            return
        self._schedule_for_signal("character_changed")

    def _on_channel_changed(self, workspace_path: Path, channel_id: int) -> None:
        del channel_id
        if workspace_path != self._workspace_path:
            return
        self._schedule_for_signal("channel_changed")

    def _schedule_for_signal(self, signal: str) -> None:
        for resource in self._registry.resources_for_signal(signal):
            self._schedule_emit(resource, signal)

    def _schedule_emit(self, resource: str, reason: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        old = self._debounce_tasks.pop(resource, None)
        if old is not None and not old.done():
            # Cancel prior wake-up; typical debounce. If cancellation races with a task
            # already inside `_flush`, the old task is discarded — acceptable because the
            # next scheduled emit uses a fresh bump + reason after the sleep.
            old.cancel()

        task = loop.create_task(
            self._debounced_emit(resource, reason),
            name=f"resource-changed-{resource}",
        )
        self._debounce_tasks[resource] = task

    async def _debounced_emit(self, resource: str, reason: str) -> None:
        try:
            await asyncio.sleep(self.DEBOUNCE_SECONDS)
            await self._flush(resource, reason)
        except asyncio.CancelledError:
            raise
        finally:
            existing = self._debounce_tasks.get(resource)
            if existing is asyncio.current_task():
                self._debounce_tasks.pop(resource, None)

    async def _flush(self, resource: str, reason: str) -> None:
        recipients = self._targeting.device_ids_for_connected(self._connected_device_ids)
        if not recipients:
            return

        sync_version = self._version_store.bump(resource)
        data: dict[str, Any] = {
            "resource": resource,
            "reason": reason,
            "resource_sync_version": sync_version,
            # TODO(ids/scope): add optional ``ids`` + ``scope`` when selective invalidation
            # and per-user targeting are wired (see docs/resource-sync.md §4).
        }

        for device_id in recipients:
            await self._emit_outbound(
                EnvelopeFactory.resource_changed_event(
                    channel=MANDATORY_CHANNEL_NAME,
                    recipient_id=device_id,
                    data=data,
                )
            )

        log.info(
            "⬆️ Resource hints sent — device nodes · event:resource.changed",
            resource=resource,
            reason=reason,
            sync_version=sync_version,
            device_count=len(recipients),
        )
