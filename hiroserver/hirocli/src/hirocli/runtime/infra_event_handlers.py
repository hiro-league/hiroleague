"""Infrastructure-level channel event handlers.

Handles pairing requests, gateway connectivity tracking, and other infrastructure
concerns: events a channel plugin sends as itself, registered in the extension
manager's one event registry (open to channel plugins only).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from hiro_commons.attestation import create_device_attestation
from hiro_commons.log import Logger

from hirocli.constants import DEVICE_ID_PREFIX, DEVICE_ID_SUFFIX_LENGTH
from hirocli.domain.config import mark_connected, mark_disconnected
from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hirocli.domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from hirocli.domain.extensions import KIND_CHANNEL
from hirocli.domain.pairing import (
    ApprovedDevice,
    clear_pairing_session,
    load_pairing_session,
    paired_device_ids,
    upsert_approved_device,
)

if TYPE_CHECKING:
    from hirocli.runtime.extension_manager import ExtensionManager
    from hirocli.runtime.resource_change_broadcaster import ResourceChangeBroadcaster
    from hirocli.runtime.server_context import ServerContext

log = Logger.get("INFRA")

_CHANNELS_ONLY: frozenset[str] = frozenset({KIND_CHANNEL})


class InfraEventHandlers:
    """Handles infrastructure channel events: pairing, gateway connectivity."""

    def __init__(self, ctx: ServerContext) -> None:
        self._ctx = ctx
        self._extensions: ExtensionManager | None = None
        self._resource_change_broadcaster: ResourceChangeBroadcaster | None = None

    def set_extension_manager(self, manager: ExtensionManager) -> None:
        self._extensions = manager
        # A device paired or removed (the admin, the CLI): the gateway hears the new list at once.
        get_domain_event_bus().subscribe(DomainEventType.DEVICES_CHANGED, self._on_devices_changed)

    async def _on_devices_changed(self, event: DomainEvent) -> None:
        if event.workspace_path == self._ctx.workspace_path:
            await self.send_allowed_devices()

    async def send_allowed_devices(self) -> None:
        """Tell the gateway, through the devices channel, which devices may connect: it refuses and cuts off the rest,
        so a device removed in the admin stops at once instead of when its 30-day pass runs out."""
        if self._extensions is None:
            return
        ids = sorted(paired_device_ids(self._ctx.workspace_path))
        await self._extensions.send_event_to_channel(
            MANDATORY_CHANNEL_NAME, "allowed_devices", {"device_ids": ids},
        )

    def set_resource_change_broadcaster(self, broadcaster: ResourceChangeBroadcaster) -> None:
        self._resource_change_broadcaster = broadcaster

    def register_all(self, manager: ExtensionManager) -> None:
        manager.register_event_handler("pairing_request", self.handle_pairing_request, _CHANNELS_ONLY)
        manager.register_event_handler("gateway_connected", self.handle_gateway_connected, _CHANNELS_ONLY)
        manager.register_event_handler("gateway_disconnected", self.handle_gateway_disconnected, _CHANNELS_ONLY)
        manager.register_event_handler("device_connected", self.handle_device_connected, _CHANNELS_ONLY)
        manager.register_event_handler("device_disconnected", self.handle_device_disconnected, _CHANNELS_ONLY)
        # §5.4 — channels surface pairing (QR/token) + connection status generically;
        # cache the latest per channel on the shared ctx for the admin routes to read.
        manager.register_event_handler("channel.pairing", self.handle_channel_pairing, _CHANNELS_ONLY)
        manager.register_event_handler("channel.status", self.handle_channel_status, _CHANNELS_ONLY)

    def _channel_name(self, extension_id: str) -> str:
        """The name of the channel plugin that sent the event (the manager knows who signed in)."""
        return self._extensions.name_of(extension_id) if self._extensions is not None else ""

    async def handle_channel_pairing(self, extension_id: str, _event: str, data: dict[str, Any]) -> None:
        channel = self._channel_name(extension_id)
        # QR channels push the pairing code here; token/oauth channels omit it (the
        # code is user-entered, not server-issued).
        code = str(data.get("qr") or data.get("code") or "")
        if not channel or not code:
            return
        st = self._ctx.channel_status.setdefault(channel, {})
        st["qr"] = code
        st["qr_at"] = datetime.now(UTC).isoformat()
        st["pairing_kind"] = str(data.get("kind") or "qr")

    async def handle_channel_status(self, extension_id: str, _event: str, data: dict[str, Any]) -> None:
        channel = self._channel_name(extension_id)
        if not channel:
            return
        state = str(data.get("state") or "")
        st = self._ctx.channel_status.setdefault(channel, {})
        st["state"] = state
        st["state_at"] = datetime.now(UTC).isoformat()
        account = data.get("account")
        if account:
            st["account"] = str(account)
        # Keep any diagnostic detail the plugin attached (reason/code/expire/message
        # for logged_out/banned/error, backoff for reconnecting) so the admin UI can
        # explain a terminal state instead of showing a bare status word.
        detail = {k: v for k, v in data.items() if k not in ("state", "account", "channel")}
        st["detail"] = detail
        # Once linked, the QR is stale — drop it so the UI stops showing it.
        if state in ("connected", "paired"):
            st.pop("qr", None)

    async def handle_pairing_request(self, _extension_id: str, _event: str, data: dict[str, Any]) -> None:
        if self._extensions is None:
            return
        request_id = data.get("request_id")
        pairing_code = data.get("pairing_code")
        device_public_key = data.get("device_public_key")
        device_name_raw = data.get("device_name")
        device_name = device_name_raw if isinstance(device_name_raw, str) and device_name_raw else None

        if not isinstance(request_id, str) or not request_id:
            return
        if not isinstance(pairing_code, str) or not pairing_code:
            await self._extensions.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "invalid_pairing_code"},
            )
            return
        if not isinstance(device_public_key, str) or not device_public_key:
            await self._extensions.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "invalid_device_public_key"},
            )
            return

        session = load_pairing_session(self._ctx.workspace_path)
        if session is None:
            await self._extensions.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "no_active_pairing_session"},
            )
            return

        if (not session.is_valid()) or (session.code != pairing_code):
            await self._extensions.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "pairing_code_invalid_or_expired"},
            )
            return

        device_id = f"{DEVICE_ID_PREFIX}{uuid.uuid4().hex[:DEVICE_ID_SUFFIX_LENGTH]}"
        attestation = create_device_attestation(
            self._ctx.desktop_private_key,
            device_id=device_id,
            device_public_key_b64=device_public_key,
            expires_days=self._ctx.config.attestation_expires_days,
        )
        blob = json.loads(attestation["blob"])
        expires_at_raw = blob.get("expires_at")
        expires_at = None
        if isinstance(expires_at_raw, str):
            try:
                expires_at = datetime.fromisoformat(
                    expires_at_raw.replace("Z", "+00:00")
                ).astimezone(UTC)
            except Exception as exc:
                log.debug("Could not read the attestation's expiry — the device is stored without one", error=str(exc))
                expires_at = None

        upsert_approved_device(
            self._ctx.workspace_path,
            ApprovedDevice(
                device_id=device_id,
                device_public_key=device_public_key,
                paired_at=datetime.now(UTC),
                expires_at=expires_at,
                metadata={"source": "gateway_pairing"},
                device_name=device_name,
            ),
        )
        clear_pairing_session(self._ctx.workspace_path)
        # The gateway must list the new device before the device signs in with its pass, a moment after this answer.
        await self.send_allowed_devices()
        await self._extensions.send_event_to_channel(
            "devices", "pairing_response",
            {
                "request_id": request_id,
                "status": "approved",
                "device_id": device_id,
                "attestation": attestation,
            },
        )

    async def handle_gateway_connected(self, _extension_id: str, _event: str, data: dict[str, Any]) -> None:
        gateway_url = str(data.get("gateway_url") or self._ctx.config.gateway_url)
        mark_connected(self._ctx.workspace_path, gateway_url)
        await self.send_allowed_devices()

    async def handle_gateway_disconnected(self, _extension_id: str, _event: str, _data: dict[str, Any]) -> None:
        mark_disconnected(self._ctx.workspace_path)
        if self._resource_change_broadcaster is not None:
            await self._resource_change_broadcaster.clear_connected_devices()
            log.fineinfo("🔌 Recipients cleared — HiroServer · gateway:down")

    async def handle_device_connected(self, _extension_id: str, _event: str, data: dict[str, Any]) -> None:
        device_id = data.get("device_id")
        if not isinstance(device_id, str) or not device_id:
            return
        if self._resource_change_broadcaster is not None:
            await self._resource_change_broadcaster.handle_device_connected(device_id)
            log.fineinfo(
                f"🔌 Recipient added — {device_id} · transport:device-up",
                device_id=device_id,
            )

    async def handle_device_disconnected(self, _extension_id: str, _event: str, data: dict[str, Any]) -> None:
        device_id = data.get("device_id")
        if not isinstance(device_id, str) or not device_id:
            return
        if self._resource_change_broadcaster is not None:
            await self._resource_change_broadcaster.handle_device_disconnected(device_id)
            log.fineinfo(
                f"🔌 Recipient removed — {device_id} · transport:device-down",
                device_id=device_id,
            )
