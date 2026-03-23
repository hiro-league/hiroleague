"""ServerContext — shared runtime state for all server components.

Every runtime component (ChannelManager, CommunicationManager, AgentManager,
HTTP server, admin UI, etc.) receives a single ServerContext instead of
individual workspace_path / config / stop_event parameters.

This replaces the previous pattern of threading workspace_path through every
constructor and the ad-hoc app.state.* bag on the FastAPI instance.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hiro_commons.log import Logger

from hirocli.domain.config import Config, resolve_log_dir
from hirocli.domain.pairing import get_device_name

log = Logger.get("CTX")


class DeviceNameResolver:
    """Shared cache for device_id → friendly name lookups.

    Previously duplicated independently inside both CommunicationManager
    and ChannelManager with identical logic.
    """

    def __init__(self, workspace_path: Path) -> None:
        self._workspace_path = workspace_path
        self._cache: dict[str, str | None] = {}

    def resolve(self, device_id: str) -> str:
        """Return the paired device_name if set, otherwise the raw device_id."""
        if not device_id or device_id == "server":
            return device_id or "?"
        if device_id not in self._cache:
            self._cache[device_id] = get_device_name(self._workspace_path, device_id)
        name = self._cache[device_id]
        return name if name else device_id

    def invalidate(self, device_id: str | None = None) -> None:
        """Drop cached name(s) so the next resolve() hits the DB."""
        if device_id is None:
            self._cache.clear()
        else:
            self._cache.pop(device_id, None)


@dataclass
class ServerContext:
    """Immutable-ish bag of shared state for all runtime server components.

    Constructed once at server startup by the composition root
    (server_process.py) and passed to every component.
    """

    workspace_path: Path
    workspace_name: str
    config: Config
    stop_event: asyncio.Event
    desktop_private_key: Ed25519PrivateKey
    log_dir: Path = field(init=False)
    device_names: DeviceNameResolver = field(init=False)

    # Mutable restart state — set by /_restart endpoint, read by shutdown handler.
    restart_requested: bool = field(default=False, init=False)
    restart_admin: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.log_dir = resolve_log_dir(self.workspace_path, self.config)
        self.device_names = DeviceNameResolver(self.workspace_path)
