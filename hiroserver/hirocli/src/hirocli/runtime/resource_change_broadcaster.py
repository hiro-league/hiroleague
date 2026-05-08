"""Emits ``resource.changed`` hints on workspace-domain mutations — Tier 1 substrate.

Subscribes to the :mod:`hirocli.domain.events` bus and translates typed domain
events into debounced fan-out of ``resource.changed`` envelopes to connected
devices. The bus owns the asyncio loop and the thread-safety story; this class
only deals with the runtime loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hiro_commons.log import Logger

from ..domain.events import (
    DomainEvent,
    DomainEventType,
    DomainEventBus,
    get_domain_event_bus,
)
from .device_targeting import DeviceTargeting
from .envelope_factory import EnvelopeFactory
from .resource_registry import ResourceRegistry
from .resource_versioning import ResourceVersionStore

EmitOutbound = Callable[..., Awaitable[None]]

log = Logger.get("RESOURCE.CHANGED")


# Map domain event types to the legacy "signal" identifiers consumed by
# ``ResourceRegistry``. Keeping the registry's vocabulary stable means the
# device-side resource list does not have to change in lockstep with bus
# refactors.
_EVENT_TO_SIGNAL: dict[str, str] = {
    DomainEventType.PREFERENCES_SAVED: "preferences_saved",
    DomainEventType.CHARACTER_CHANGED: "character_changed",
    DomainEventType.CHARACTER_PHOTO_CHANGED: "character_photo_changed",
    DomainEventType.CHANNEL_CHANGED: "channel_changed",
}


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
        bus: DomainEventBus | None = None,
    ) -> None:
        self._workspace_path = workspace_path
        self._emit_outbound = emit_outbound
        self._version_store = version_store
        self._registry = registry or ResourceRegistry()
        self._targeting = targeting or DeviceTargeting()
        self._bus = bus or get_domain_event_bus()
        self._connected_device_ids: set[str] = set()
        self._debounce_tasks: dict[str, asyncio.Task[None]] = {}

    def start(self) -> None:
        for event_type in _EVENT_TO_SIGNAL:
            self._bus.subscribe(event_type, self._on_domain_event)

    def close(self) -> None:
        for task in list(self._debounce_tasks.values()):
            if not task.done():
                task.cancel()
        self._debounce_tasks.clear()
        for event_type in _EVENT_TO_SIGNAL:
            self._bus.unsubscribe(event_type, self._on_domain_event)

    async def handle_device_connected(self, device_id: str) -> None:
        self._connected_device_ids.add(device_id)

    async def handle_device_disconnected(self, device_id: str) -> None:
        self._connected_device_ids.discard(device_id)

    async def clear_connected_devices(self) -> None:
        self._connected_device_ids.clear()

    async def _on_domain_event(self, event: DomainEvent) -> None:
        if event.workspace_path != self._workspace_path:
            return
        signal = _EVENT_TO_SIGNAL.get(event.type)
        if signal is None:
            return
        log.info("Domain signal received", event_type=event.type, signal=signal)
        self._schedule_for_signal(signal)

    def _schedule_for_signal(self, signal: str) -> None:
        resources = list(self._registry.resources_for_signal(signal))
        if not resources:
            log.debug("Signal ignored (no resources)", signal=signal)
            return
        # Per-resource emission already logs ``⬆️ Resource hints sent``; no need
        # to also log "marked dirty" between signal-received and flush.
        for resource in resources:
            self._schedule_emit(resource, signal)

    def _schedule_emit(self, resource: str, reason: str) -> None:
        # Subscribers always run on the bus's attached loop, so this is safe.
        loop = asyncio.get_running_loop()

        old = self._debounce_tasks.pop(resource, None)
        if old is not None and not old.done():
            # Cancel prior wake-up; typical debounce. If cancellation races with a task
            # already inside `_flush`, the old task is discarded — acceptable because the
            # next scheduled emit uses a fresh bump + reason after the sleep.
            old.cancel()
            log.debug(
                f"Debounce coalesced — resource:{resource}",
                reason=reason,
            )

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
        except Exception as exc:
            log.error(
                f"❌ Resource hint failed — resource:{resource}",
                reason=reason,
                error=str(exc),
                exc_info=True,
            )
        finally:
            existing = self._debounce_tasks.get(resource)
            if existing is asyncio.current_task():
                self._debounce_tasks.pop(resource, None)

    async def _flush(self, resource: str, reason: str) -> None:
        recipients = self._targeting.device_ids_for_connected(self._connected_device_ids)
        if not recipients:
            log.debug(
                f"Hint skipped (no devices) — resource:{resource}",
                reason=reason,
            )
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
