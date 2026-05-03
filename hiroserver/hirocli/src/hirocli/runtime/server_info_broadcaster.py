from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

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
from ..domain.server_info import build_server_info_snapshot
from .envelope_factory import EnvelopeFactory

log = Logger.get("SERVER.INFO")

EmitOutbound = Callable[..., Awaitable[None]]


class ServerInfoBroadcaster:
    """Pushes ``server.info`` snapshots to connected devices."""

    def __init__(self, workspace_path: Path, emit_outbound: EmitOutbound) -> None:
        self._workspace_path = workspace_path
        self._emit_outbound = emit_outbound
        self._connected_device_ids: set[str] = set()

    def start(self) -> None:
        subscribe_preferences_saved(self.on_preferences_saved)
        subscribe_character_changes(self.on_character_changed)
        subscribe_channel_changes(self.on_channel_changed)

    def close(self) -> None:
        unsubscribe_preferences_saved(self.on_preferences_saved)
        unsubscribe_character_changes(self.on_character_changed)
        unsubscribe_channel_changes(self.on_channel_changed)

    async def handle_device_connected(self, device_id: str) -> None:
        self._connected_device_ids.add(device_id)
        await self.push_to_device(device_id)

    async def handle_device_disconnected(self, device_id: str) -> None:
        self._connected_device_ids.discard(device_id)

    async def clear_connected_devices(self) -> None:
        self._connected_device_ids.clear()

    async def push_to_device(self, device_id: str) -> None:
        snapshot = build_server_info_snapshot(self._workspace_path).model_dump(mode="json")
        await self._emit_outbound(
            EnvelopeFactory.server_info_event(
                channel=MANDATORY_CHANNEL_NAME,
                recipient_id=device_id,
                snapshot=snapshot,
            )
        )
        log.info(
            "⬆️ Server info sent — device node · event:server.info",
            device_id=device_id,
            channels=len(snapshot.get("channels") or []),
        )

    async def broadcast(self) -> None:
        recipients = sorted(self._connected_device_ids)
        if not recipients:
            return
        snapshot = build_server_info_snapshot(self._workspace_path).model_dump(mode="json")
        for device_id in recipients:
            await self._emit_outbound(
                EnvelopeFactory.server_info_event(
                    channel=MANDATORY_CHANNEL_NAME,
                    recipient_id=device_id,
                    snapshot=snapshot,
                )
            )
        log.info(
            "⬆️ Server info broadcast — device nodes · event:server.info",
            device_count=len(recipients),
            channels=len(snapshot.get("channels") or []),
        )

    def on_preferences_saved(self, workspace_path: Path, prefs: WorkspacePreferences) -> None:
        del prefs
        if workspace_path != self._workspace_path:
            return
        self._schedule_broadcast("preferences_saved")

    def on_character_changed(self, workspace_path: Path, character_id: str) -> None:
        del character_id
        if workspace_path != self._workspace_path:
            return
        self._schedule_broadcast("character_changed")

    def on_channel_changed(self, workspace_path: Path, channel_id: int) -> None:
        del channel_id
        if workspace_path != self._workspace_path:
            return
        self._schedule_broadcast("channel_changed")

    def _schedule_broadcast(self, reason: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._broadcast_with_logging(reason), name=f"server-info-{reason}")

    async def _broadcast_with_logging(self, reason: str) -> None:
        try:
            await self.broadcast()
        except Exception as exc:
            log.error(
                "❌ Server info broadcast failed — device nodes · event:server.info",
                reason=reason,
                error=str(exc),
                exc_info=True,
            )
