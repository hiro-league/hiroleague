"""Device pairing and approved-device list — wraps device tools; no NiceGUI (guidelines §1.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hirocli.tools.device import DeviceAddTool, DeviceListTool, DeviceRevokeTool

from hirocli.admin.shared.result import Result


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
            return Result.failure(str(exc))
        return Result.success(list(result.devices))

    def generate_pairing_code(self, workspace_id: str | None) -> Result[DevicePairingData]:
        if not workspace_id:
            return Result.failure("No workspace selected.")
        try:
            raw = DeviceAddTool().execute(workspace=workspace_id)
        except Exception as exc:
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
            return Result.failure(str(exc))
        if not result.removed:
            return Result.failure(f"Device '{device_id}' was not found or already revoked.")
        return Result.success("Device revoked.")
