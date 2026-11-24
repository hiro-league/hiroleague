"""Device management tools.

Four operations: generate a pairing code (for a person), list approved devices, say whose a device is, revoke one.
Both the CLI (commands/device.py) and the AI agent call these directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.config import load_config
from ..domain.pairing import (
    create_pairing_session,
    load_approved_devices,
    revoke_approved_device,
    save_pairing_session,
    set_device_person,
)
from ..domain.people import get_person, list_people
from ..domain.talkers import owner_person
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam
from .rights import ToolRight


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class DeviceAddResult:
    code: str
    expires_at: str
    gateway_url: str = ""

    @property
    def qr_payload(self) -> str:
        """JSON string to embed in the pairing QR code."""
        return json.dumps(
            {"gateway_url": self.gateway_url, "code": self.code, "expires_at": self.expires_at},
            separators=(",", ":"),
        )


@dataclass
class DeviceAssignResult:
    device_id: str
    person_id: str
    person_name: str


def _person_or_owner(workspace_path: Path, person_id: str | None) -> str:
    """Whose a device paired now will be: the person named, else the owner (Permissions phase 3)."""
    if person_id:
        if get_person(workspace_path, person_id) is None:
            raise ValueError(f"Nobody in the family list has the id {person_id}.")
        return person_id
    owner = owner_person(list_people(workspace_path))
    return owner.person_id if owner else ""


@dataclass
class DeviceListResult:
    devices: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DeviceRevokeResult:
    removed: bool
    device_id: str


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class DeviceAddTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "device_add"
    description = "Generate a short-lived pairing code to onboard a new mobile device"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
        "ttl_seconds": ToolParam(int, "Pairing code lifetime in seconds", required=False),
        "code_length": ToolParam(int, "Pairing code length in digits", required=False),
        "person_id": ToolParam(str, "Whose the device will be (default: the owner)", required=False),
    }

    def execute(
        self,
        workspace: str | None = None,
        ttl_seconds: int | None = None,
        code_length: int | None = None,
        person_id: str | None = None,
    ) -> DeviceAddResult:
        workspace_path = _resolve_path(workspace)
        config = load_config(workspace_path)
        session = create_pairing_session(
            code_length=code_length or config.pairing_code_length,
            ttl_seconds=ttl_seconds or config.pairing_code_ttl_seconds,
            person_id=_person_or_owner(workspace_path, person_id),
        )
        save_pairing_session(workspace_path, session)
        return DeviceAddResult(
            code=session.code,
            expires_at=session.expires_at.isoformat().replace("+00:00", "Z"),
            gateway_url=config.gateway_url,
        )


class DeviceListTool(Tool):
    name = "device_list"
    right = ToolRight("devices", "see")
    description = "List all approved paired mobile devices"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> DeviceListResult:
        workspace_path = _resolve_path(workspace)
        devices = load_approved_devices(workspace_path)
        names = {p.person_id: p.name for p in list_people(workspace_path)}
        return DeviceListResult(
            devices=[
                {
                    "device_id": d.device_id,
                    "device_name": d.device_name,
                    "paired_at": d.paired_at.isoformat().replace("+00:00", "Z"),
                    "expires_at": (
                        d.expires_at.isoformat().replace("+00:00", "Z")
                        if d.expires_at
                        else None
                    ),
                    # Permissions phase 3: whose it is, by name too (the Devices page needs no right to People)
                    "person_id": d.person_id,
                    "person_name": names.get(d.person_id, ""),
                }
                for d in devices
            ]
        )


class DeviceAssignTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "device_assign"
    description = "Say whose a paired device is: it then shows and writes only that person's conversations"
    params = {
        "device_id": ToolParam(str, "Device ID"),
        "person_id": ToolParam(str, "The person it belongs to"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, device_id: str, person_id: str, workspace: str | None = None) -> DeviceAssignResult:
        workspace_path = _resolve_path(workspace)
        person = get_person(workspace_path, person_id)
        if person is None:
            raise ValueError(f"Nobody in the family list has the id {person_id}.")
        if not set_device_person(workspace_path, device_id, person.person_id):
            raise ValueError(f"No paired device {device_id}.")
        return DeviceAssignResult(device_id=device_id, person_id=person.person_id, person_name=person.name)


class DeviceRevokeTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "device_revoke"
    description = "Revoke a previously approved paired device"
    params = {
        "device_id": ToolParam(str, "Device ID to revoke"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, device_id: str, workspace: str | None = None) -> DeviceRevokeResult:
        workspace_path = _resolve_path(workspace)
        removed = revoke_approved_device(workspace_path, device_id)
        return DeviceRevokeResult(removed=removed, device_id=device_id)
