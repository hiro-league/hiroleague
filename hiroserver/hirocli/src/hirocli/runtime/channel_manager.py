"""ChannelManager — hirocli-side orchestrator for channel plugins.

Responsibilities:
  - Runs a local WebSocket server on plugin_port (default 18081).
  - Spawns a subprocess for each enabled channel on startup.
  - Accepts JSON-RPC connections from channel plugins.
  - Dispatches incoming channel.receive / channel.event notifications.
  - Routes channel.send / channel.configure / channel.status to plugins.
  - Terminates subprocesses on shutdown.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed
from hiro_commons.log import Logger
from hiro_commons.process import (
    is_running,
    kill_process,
    read_channel_pid,
    remove_channel_pid,
    write_channel_pid,
)

from hiro_channel_sdk.constants import (
    JSONRPC_ERROR_METHOD_NOT_FOUND,
    METHOD_CONFIGURE,
    METHOD_EVENT,
    METHOD_RECEIVE,
    METHOD_REGISTER,
    METHOD_SEND,
    METHOD_STATUS,
    METHOD_STOP,
    WS_CLOSE_CHANNEL_REPLACED,
)
from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hiro_commons.constants.network import DEFAULT_LOCALHOST
from hiro_commons.constants.timing import DEFAULT_PING_INTERVAL_SECONDS

from ..domain.channel_config import ChannelConfig, list_enabled_channels, load_channel_config
from ..domain.config import Config, resolve_log_dir
from ..domain.pairing import get_device_name
from .. import rpc_helpers as rpc

log = Logger.get("CHANNEL_MAN")


@dataclass
class _ConnectedChannel:
    name: str
    version: str
    description: str
    ws: ServerConnection
    pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)


class ChannelManager:
    """Manages the lifecycle of channel plugins as subprocesses."""

    def __init__(
        self,
        config: Config,
        workspace_path: Path,
        stop_event: asyncio.Event,
        on_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._workspace_path = workspace_path
        self._stop_event = stop_event
        self._on_message = on_message
        self._on_event = on_event
        self._channels: dict[str, _ConnectedChannel] = {}
        self._subprocesses: list[subprocess.Popen[bytes]] = []
        # Cache device_id → device_name to avoid repeated DB hits per log call.
        self._device_name_cache: dict[str, str | None] = {}
        self._host = DEFAULT_LOCALHOST
        self._port = config.plugin_port

    # ------------------------------------------------------------------
    # Main coroutine
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the plugin WS server and spawn enabled channel subprocesses."""
        async with websockets.serve(
            self._handle_connection, self._host, self._port
        ):
            log.info(f"Channel Manager listening at ws://{self._host}:{self._port}")
            await self._spawn_channels()
            await self._stop_event.wait()
            await self._shutdown_channels()

        log.info("Channel Manager shut down")

    # ------------------------------------------------------------------
    # Subprocess management
    # ------------------------------------------------------------------

    async def _spawn_channels(self) -> None:
        channels = list_enabled_channels(self._workspace_path)
        if not channels:
            log.warning("No enabled channel plugins configured")
            return

        hiro_ws = f"ws://{self._host}:{self._port}"
        for ch in channels:
            await self._spawn_one(ch, hiro_ws)

    async def _spawn_one(self, ch: ChannelConfig, hiro_ws: str) -> None:
        log_dir = resolve_log_dir(self._workspace_path, self._config)
        cmd = ch.effective_command() + [
            "--hiro-ws", hiro_ws,
            "--log-dir", str(log_dir),
        ]
        self._kill_previous_channel(ch.name)
        log.info(f"Spawning channel plugin: {ch.name}", cmd=cmd)
        try:
            if sys.platform == "win32":
                proc = subprocess.Popen(
                    cmd,
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        | subprocess.CREATE_NO_WINDOW
                    ),
                    close_fds=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    close_fds=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self._subprocesses.append(proc)
            write_channel_pid(self._workspace_path, ch.name, proc.pid)
        except FileNotFoundError:
            log.error(
                "Channel command not found",
                cmd=cmd[0],
                hint=f"hirocli channel install {ch.name}",
            )
        except Exception as exc:
            log.error(f"Failed to spawn channel plugin: {ch.name}", error=str(exc))

    def _kill_previous_channel(self, channel_name: str) -> None:
        pid = read_channel_pid(self._workspace_path, channel_name)
        if pid is None:
            return
        if is_running(pid):
            log.info(f"Stopping previous channel plugin: {channel_name}", pid=pid)
            kill_process(pid)
        remove_channel_pid(self._workspace_path, channel_name)

    async def _shutdown_channels(self) -> None:
        for ch in list(self._channels.values()):
            try:
                await ch.ws.send(rpc.build_notification(METHOD_STOP, {}))
            except Exception:
                pass

        await asyncio.sleep(1)
        for proc in self._subprocesses:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

        channels = list_enabled_channels(self._workspace_path)
        for ch in channels:
            remove_channel_pid(self._workspace_path, ch.name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _device_label(self, device_id: str) -> str:
        """Return 'DeviceName (device_id)' when a name is known, else just device_id."""
        if device_id not in self._device_name_cache:
            self._device_name_cache[device_id] = get_device_name(
                self._workspace_path, device_id
            )
        name = self._device_name_cache[device_id]
        return f"{name} ({device_id})" if name else device_id

    # ------------------------------------------------------------------
    # WebSocket connection handler
    # ------------------------------------------------------------------

    async def _handle_connection(self, ws: ServerConnection) -> None:
        channel_name: str | None = None
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("Invalid JSON from plugin", raw=str(raw)[:200])
                    continue

                if "method" not in data:
                    await self._handle_response(channel_name, data)
                    continue

                method: str = data["method"]
                params: dict[str, Any] = data.get("params", {})
                req_id: Any = data.get("id")

                match method:
                    case _ if method == METHOD_REGISTER:
                        channel_name = params["name"]
                        prev = self._channels.get(channel_name)
                        if prev is not None and prev.ws is not ws:
                            log.warning(
                                "Duplicate channel registration detected, replacing previous",
                                channel=channel_name, previous_channel=prev.name if prev else "unknown"
                            )
                            try:
                                await prev.ws.send(rpc.build_notification(METHOD_STOP, {}))
                            except Exception:
                                pass
                            try:
                                await prev.ws.close(code=WS_CLOSE_CHANNEL_REPLACED, reason="replaced by newer registration")
                            except Exception:
                                pass
                        self._channels[channel_name] = _ConnectedChannel(
                            name=channel_name,
                            version=params.get("version", "?"),
                            description=params.get("description", ""),
                            ws=ws,
                        )
                        log.info(
                            f"Channel ({channel_name}) registered",
                            channel=channel_name,
                            version=params.get("version", "?"),
                        )
                        await self._push_config(channel_name)

                    case _ if method == METHOD_RECEIVE:
                        sender_id = params.get("routing", {}).get("sender_id", "")
                        device = self._device_label(sender_id) if sender_id else "unknown"
                        log.info(
                            f"Message received via channel ({channel_name})",
                            channel=channel_name,
                            device=device,
                        )
                        if self._on_message:
                            try:
                                await self._on_message(params)
                            except Exception as exc:
                                log.error(
                                    "on_message handler error",
                                    channel=channel_name,
                                    device=device,
                                    error=str(exc),
                                    exc_info=True,
                                )

                    case _ if method == METHOD_EVENT:
                        event_name = params.get("event")
                        event_data = params.get("data", {})                        
                        log.info(
                            f"Channel ({channel_name}) event received: {event_name}",
                            event_data=event_data,
                        )
                        if self._on_event and isinstance(event_name, str):
                            try:
                                await self._on_event(event_name, event_data)
                            except Exception as exc:
                                log.error(
                                    f"on_event handler error for channel ({channel_name})",
                                    error=str(exc),
                                    exc_info=True,
                                )
                    case _:
                        log.warning(
                            f"Unknown method from channel ({channel_name})",
                            method=method,
                        )
                        if req_id is not None:
                            await ws.send(
                                rpc.build_error(
                                    JSONRPC_ERROR_METHOD_NOT_FOUND,
                                    f"Method not found: {method}",
                                    req_id,
                                )
                            )

        except ConnectionClosed:
            log.warning(f"Channel ({channel_name}) connection closed")
        except Exception as exc:
            log.error(
                f"Error in channel ({channel_name}) connection",
                error=str(exc),
            )
        finally:
            if channel_name and channel_name in self._channels:
                if self._channels[channel_name].ws is ws:
                    del self._channels[channel_name]
                    log.info(f"Channel ({channel_name}) disconnected")

    async def _handle_response(
        self, channel_name: str | None, data: dict[str, Any]
    ) -> None:
        if channel_name is None:
            return
        ch = self._channels.get(channel_name)
        if ch is None:
            return
        resp_id = str(data.get("id", ""))
        fut = ch.pending.pop(resp_id, None)
        if fut and not fut.done():
            if data.get("error"):
                fut.set_exception(RuntimeError(data["error"]["message"]))
            else:
                fut.set_result(data.get("result"))

    async def _push_config(self, channel_name: str) -> None:
        cfg = load_channel_config(self._workspace_path, channel_name)
        payload = dict(cfg.config) if cfg else {}
        if channel_name == MANDATORY_CHANNEL_NAME:
            payload.setdefault("gateway_url", self._config.gateway_url)
            payload.setdefault("device_id", self._config.device_id)
            payload.setdefault("ping_interval", DEFAULT_PING_INTERVAL_SECONDS)
        if payload:
            await self.configure_channel(channel_name, payload)

    # ------------------------------------------------------------------
    # Outbound API (hirocli → plugin)
    # ------------------------------------------------------------------

    async def send_to_channel(
        self, channel_name: str, message: dict[str, Any]
    ) -> None:
        ch = self._channels.get(channel_name)
        if ch is None:
            log.warning(f"Cannot send to channel ({channel_name}) — not connected")
            return
        await ch.ws.send(rpc.build_notification(METHOD_SEND, message))
        # Log the message ID and recipient device for end-to-end tracing.
        routing = message.get("routing", {}) if isinstance(message, dict) else {}
        msg_id = routing.get("id", "-")
        recipient_id = routing.get("recipient_id", "")
        device = self._device_label(recipient_id) if recipient_id else "unknown"
        log.info(f"Message sent to channel ({channel_name})", msg_id=msg_id, device=device)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for ch in list(self._channels.values()):
            try:
                await ch.ws.send(rpc.build_notification(METHOD_SEND, message))
            except Exception as exc:
                log.warning(f"Failed to broadcast to channel ({ch.name})", error=str(exc))

    async def configure_channel(
        self, channel_name: str, config: dict[str, Any]
    ) -> None:
        ch = self._channels.get(channel_name)
        if ch is None:
            return
        await ch.ws.send(
            rpc.build_notification(METHOD_CONFIGURE, {"config": config})
        )

    async def send_event_to_channel(
        self, channel_name: str, event: str, data: dict[str, Any]
    ) -> None:
        ch = self._channels.get(channel_name)
        if ch is None:
            log.warning(
                f"Cannot send event to channel ({channel_name}) — not connected"
            )
            return
        await ch.ws.send(
            rpc.build_notification(
                METHOD_EVENT,
                {"event": event, "data": data},
            )
        )

    async def probe_channel(self, channel_name: str) -> dict[str, Any] | None:
        ch = self._channels.get(channel_name)
        if ch is None:
            return None
        from uuid import uuid4

        req_id = uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        ch.pending[req_id] = fut
        await ch.ws.send(rpc.build_request(METHOD_STATUS, request_id=req_id))
        try:
            return await asyncio.wait_for(fut, timeout=5.0)
        except asyncio.TimeoutError:
            ch.pending.pop(req_id, None)
            return None

    def get_connected_channels(self) -> list[str]:
        return list(self._channels.keys())

    def get_channel_info(self) -> list[dict[str, str]]:
        return [
            {
                "name": ch.name,
                "version": ch.version,
                "description": ch.description,
            }
            for ch in self._channels.values()
        ]
