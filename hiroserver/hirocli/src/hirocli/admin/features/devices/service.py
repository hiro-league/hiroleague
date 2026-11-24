"""Device pairing and approved-device operations for the admin API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hirocli.tools.device import DeviceAddTool, DeviceAssignTool, DeviceListTool, DeviceRevokeTool

from hirocli.admin.shared.result import Result
from hiro_commons.log import Logger

log = Logger.get("ADMIN.DEVICES")


@dataclass(frozen=True)
class DevicePairingData:
    """Plain data for the pairing dialog (QR + labels)."""

    code: str
    expires_at: str
    gateway_url: str
    qr_payload: str


class DeviceService:
    """Facade over device tools."""

    def list_devices(self, workspace_id: str | None) -> Result[list[dict[str, Any]]]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            result = DeviceListTool().execute(workspace=workspace_id)
        except Exception as exc:
            log.warning("⚠️ Devices list failed — HiroAdmin · devices", workspace_id=workspace_id, error=str(exc), exc_info=True)
            return Result.failure(str(exc))
        return Result.success(list(result.devices))

    def assign_device(self, device_id: str, person_id: str, workspace_id: str | None) -> Result[str]:
        """Say whose a paired device is (Permissions phase 3)."""
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            done = DeviceAssignTool().execute(device_id=device_id, person_id=person_id, workspace=workspace_id)
        except ValueError as exc:
            # The tool's words for a person: no such device or person
            return Result.failure(str(exc))
        log.info(f"Devices: {done.device_id} is now {done.person_name}'s", device_id=done.device_id, person_id=done.person_id)
        return Result.success(f"It is now {done.person_name}'s device.")

    def generate_pairing_code(self, workspace_id: str | None, person_id: str | None = None) -> Result[DevicePairingData]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            raw = DeviceAddTool().execute(workspace=workspace_id, person_id=person_id)
        except Exception as exc:
            log.warning("⚠️ Device pairing code failed — HiroAdmin · devices", workspace_id=workspace_id, error=str(exc), exc_info=True)
            return Result.failure(str(exc))
        return Result.success(
            DevicePairingData(
                code=raw.code,
                expires_at=raw.expires_at,
                gateway_url=raw.gateway_url or "",
                qr_payload=raw.qr_payload,
            )
        )

    def revoke_device(self, device_id: str, workspace_id: str | None) -> Result[str]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        if not device_id:
            return Result.failure("Device ID is required.")
        try:
            result = DeviceRevokeTool().execute(device_id=device_id, workspace=workspace_id)
        except Exception as exc:
            log.warning(
                "⚠️ Device revoke failed — HiroAdmin · devices",
                device_id=device_id,
                workspace_id=workspace_id,
                error=str(exc),
                exc_info=True,
            )
            return Result.failure(str(exc))
        if not result.removed:
            return Result.failure(f"Device '{device_id}' was not found or already revoked.")
        return Result.success("Device revoked.")
