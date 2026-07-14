"""ChannelManager — Hiro-side orchestrator for channel plugins.

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
from typing import TYPE_CHECKING, Any

import websockets
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed
from hiro_commons.log import Logger, log_scope
from hiro_commons.process import (
    is_running,
    kill_process,
    read_channel_pid,
    remove_channel_pid,
    write_channel_pid,
)

from hiro_channel_sdk.constants import (
    JSONRPC_ERROR_METHOD_NOT_FOUND,
    MESSAGE_TYPE_MESSAGE,
    MESSAGE_TYPE_STREAM,
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
from hiro_channel_sdk.log_scope_fields import (
    TRAFFIC_CLASS_INFRA_EVENT,
    TRAFFIC_CLASS_INFRA_TRANSPORT,
    unified_message_log_scope,
)
from hiro_channel_sdk.models import UnifiedMessage

from ..domain.channel_config import ChannelConfig, list_enabled_channels, load_channel_config
from .. import rpc_helpers as rpc

# Shared comm-log helpers (arrows, kind, content_hint) — same vocabulary as CommunicationManager.
from .comm_log import LOG_IN, LOG_OUT, comm_extras, comm_kind, routing_requests_voice_reply

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("CHANNEL_MAN")

# Routine transport churn — plugin/handler layers already log the owning transition.
_FINEINFO_CHANNEL_EVENTS = frozenset({
    "gateway_disconnected",
    "device_connected",
    "device_disconnected",
})


@dataclass
class _ConnectedChannel:
    name: str
    version: str
    description: str
    ws: ServerConnection
    # §5.1/§5.2 — the config JSON Schema + capability descriptor the plugin declared
    # at registration (None for channels that declare neither).
    config_schema: dict[str, Any] | None = None
    capabilities: dict[str, Any] | None = None
    pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)


class ChannelManager:
    """Manages the lifecycle of channel plugins as subprocesses."""

    def __init__(
        self,
        ctx: ServerContext,
        on_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._ctx = ctx
        self._on_message = on_message
        self._on_event = on_event
        self._channels: dict[str, _ConnectedChannel] = {}
        self._subprocesses: dict[str, subprocess.Popen[bytes]] = {}
        self._host = DEFAULT_LOCALHOST
        self._port = ctx.config.plugin_port

    # Late-binding setters: let the bootstrap build ChannelManager first (so it
    # can be passed as the OutboundSink to CommunicationManager), then install
    # the upstream callbacks once both managers exist.
    def set_message_handler(
        self, handler: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> None:
        self._on_message = handler

    def set_event_handler(
        self, handler: Callable[[str, dict[str, Any]], Awaitable[None]]
    ) -> None:
        self._on_event = handler

    # ------------------------------------------------------------------
    # Main coroutine
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the plugin WS server and spawn enabled channel subprocesses."""
        async with websockets.serve(
            self._handle_connection, self._host, self._port
        ):
            log.info(
                f"✅ Channel Manager listening at ws://{self._host}:{self._port}"
            )
            await self._spawn_channels()
            await self._ctx.stop_event.wait()
            await self._shutdown_channels()

        log.info("Channel Manager shut down")

    # ------------------------------------------------------------------
    # Subprocess management
    # ------------------------------------------------------------------

    async def _spawn_channels(self) -> None:
        channels = list_enabled_channels(self._ctx.workspace_path)
        if not channels:
            log.warning("No enabled channel plugins configured")
            return

        hiro_ws = f"ws://{self._host}:{self._port}"
        for ch in channels:
            await self._spawn_one(ch, hiro_ws)

    async def _spawn_one(self, ch: ChannelConfig, hiro_ws: str) -> None:
        cmd = ch.effective_command() + [
            "--hiro-ws", hiro_ws,
            "--log-dir", str(self._ctx.log_dir),
            "--log-level", self._ctx.config.log_level,
        ]
        self._kill_previous_channel(ch.name)
        log.info(f"🔌 Spawning channel plugin: {ch.name}", cmd=cmd)
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
            self._subprocesses[ch.name] = proc
            write_channel_pid(self._ctx.workspace_path, ch.name, proc.pid)
        except FileNotFoundError:
            log.error(
                "❌ Channel command not found",
                cmd=cmd[0],
                hint=f"hiro channel install {ch.name}",
            )
        except Exception as exc:
            log.error(
                f"❌ Failed to spawn channel plugin: {ch.name}", error=str(exc)
            )

    def _kill_previous_channel(self, channel_name: str) -> None:
        pid = read_channel_pid(self._ctx.workspace_path, channel_name)
        if pid is None:
            return
        if is_running(pid):
            log.info(f"Stopping previous channel plugin: {channel_name}", pid=pid)
            kill_process(pid)
        remove_channel_pid(self._ctx.workspace_path, channel_name)

    async def _shutdown_channels(self) -> None:
        for ch in list(self._channels.values()):
            try:
                await ch.ws.send(rpc.build_notification(METHOD_STOP, {}))
            except Exception:
                pass

        await asyncio.sleep(1)
        for proc in self._subprocesses.values():
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

        channels = list_enabled_channels(self._ctx.workspace_path)
        for ch in channels:
            remove_channel_pid(self._ctx.workspace_path, ch.name)

    # ------------------------------------------------------------------
    # Live single-channel lifecycle (no server restart)
    # ------------------------------------------------------------------

    async def activate(self, channel_name: str) -> None:
        """Spawn a configured channel live. No-op if it is already running.

        Registration + ``channel.configure`` happen automatically when the plugin
        connects (see ``_handle_connection`` → ``_push_config``).
        """
        existing = self._subprocesses.get(channel_name)
        if existing is not None and existing.poll() is None:
            log.info(f"Channel already running — {channel_name}")
            return
        cfg = load_channel_config(self._ctx.workspace_path, channel_name)
        if cfg is None:
            raise ValueError(f"Channel '{channel_name}' is not configured.")
        await self._spawn_one(cfg, f"ws://{self._host}:{self._port}")

    async def deactivate(self, channel_name: str) -> None:
        """Stop a running channel live: graceful ``channel.stop``, then reap.

        Authoritative teardown — a deactivated channel must stop flowing entirely:
          1. STOP notification, then **close the websocket** so the inbound receive
             loop (``_handle_connection``) stops dispatching messages to the agent
             even if the OS process lingers a moment before exiting.
          2. Reap the tracked ``Popen`` (fast path for a plugin this server spawned).
          3. Force-kill by the recorded PID with a **tree kill** — covers plugins
             spawned by a previous server run (absent from ``self._subprocesses``)
             and ``uv``-launcher children that ``proc.terminate()`` would orphan.
        """
        ch = self._channels.pop(channel_name, None)
        if ch is not None:
            try:
                await ch.ws.send(rpc.build_notification(METHOD_STOP, {}))
            except Exception as exc:  # ws may already be closed
                log.warning(f"⚠️ Stop notify failed — {channel_name}", error=str(exc))
            # Close the socket so no further channel.receive is dispatched (fix: a
            # disabled/removed channel was still processing inbound messages).
            try:
                await ch.ws.close()
            except Exception as exc:
                log.warning(f"⚠️ WS close failed — {channel_name}", error=str(exc))
        proc = self._subprocesses.pop(channel_name, None)
        if proc is not None and proc.poll() is None:
            await asyncio.sleep(0.5)  # give the plugin a moment to exit after STOP
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception as exc:
                    log.warning(f"⚠️ Terminate failed — {channel_name}", error=str(exc))
        # Authoritative reap by recorded PID (force + tree), independent of whether
        # this server instance is the one that spawned the plugin.
        pid = read_channel_pid(self._ctx.workspace_path, channel_name)
        if pid is not None and is_running(pid):
            kill_process(pid, include_tree=True)
        remove_channel_pid(self._ctx.workspace_path, channel_name)
        log.info(f"🔌 Channel deactivated — {channel_name}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _device_label(self, device_id: str) -> str:
        """Return paired device_name when set, else device_id (compact for narrow log UIs).

        Uses the shared DeviceNameResolver from ServerContext instead of a
        per-manager cache (previously duplicated in CommunicationManager).
        """
        return self._ctx.device_names.resolve(device_id)

    def _event_peer_label(self, event_data: dict[str, Any]) -> str | None:
        """Friendly device label from channel.event payloads when an id field is present."""
        d_id = event_data.get("device_id") or event_data.get("sender_device_id")
        if isinstance(d_id, str) and d_id.strip():
            return self._device_label(d_id.strip())
        return None

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
                    log.warning(
                        "⚠️ Invalid JSON from plugin", raw=str(raw)[:200]
                    )
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
                                "⚠️ Duplicate channel, replacing previous",
                                channel=channel_name,
                                previous_channel=prev.name if prev else "unknown",
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
                            config_schema=params.get("config_schema"),
                            capabilities=params.get("capabilities"),
                        )
                        # §5.1/§5.2 — persist the declared schema + capabilities so the
                        # config Tools / admin routes can validate + render generically,
                        # even from the CLI or after a restart.
                        self._persist_descriptor(channel_name, params)
                        with log_scope(
                            traffic_class=TRAFFIC_CLASS_INFRA_TRANSPORT,
                            traffic_subclass="register",
                        ):
                            log.info(
                                f"✅ Channel ({channel_name}) registered",
                                channel=channel_name,
                                version=params.get("version", "?"),
                            )
                        await self._push_config(channel_name)

                    case _ if method == METHOD_RECEIVE:
                        sender_id = params.get("routing", {}).get("sender_id", "")
                        device = self._device_label(sender_id) if sender_id else "unknown"
                        # Inject resolved device_name so downstream components can log it.
                        routing_meta = params.setdefault("routing", {}).setdefault("metadata", {})
                        routing_meta["device_name"] = device
                        # Reuse comm log helpers when params are a valid UnifiedMessage (human-first kind + content_hint).
                        try:
                            um = UnifiedMessage.model_validate(params)
                            kind = comm_kind(um)
                            # Surface per-message voice-reply intent in the log message (not only extras) for text and audio sends.
                            vr_suffix = ""
                            vr_extras: dict[str, Any] = {}
                            if um.message_type == MESSAGE_TYPE_MESSAGE:
                                vr_on = routing_requests_voice_reply(um.routing.metadata)
                                vr_suffix = " · voice_reply=yes" if vr_on else " · voice_reply=no"
                                vr_extras["voice_reply_requested"] = vr_on
                            sd, smid, smeth, stpv, stcl, stsub = unified_message_log_scope(
                                um,
                                direction="inbound",
                            )
                            with log_scope(
                                device_id=sd,
                                msg_id=smid,
                                method=smeth,
                                text_preview=stpv,
                                traffic_class=stcl,
                                traffic_subclass=stsub,
                            ):
                                log.info(
                                    f"{LOG_IN} Received — {device} · {kind}{vr_suffix}",
                                    **comm_extras(
                                        um,
                                        channel=channel_name,
                                        **vr_extras,
                                    ),
                                )
                        except Exception:
                            mt = params.get("message_type", "?")
                            log.info(
                                f"{LOG_IN} Received — {device} · {mt}",
                                channel=channel_name,
                            )
                        if self._on_message:
                            try:
                                await self._on_message(params)
                            except Exception as exc:
                                log.error(
                                    f"❌ {LOG_IN} on_message handler error — {device}",
                                    channel=channel_name,
                                    error=str(exc),
                                    exc_info=True,
                                )

                    case _ if method == METHOD_EVENT:
                        event_name = params.get("event")
                        raw_event_data = params.get("data", {})
                        peer = (
                            self._event_peer_label(raw_event_data)
                            if isinstance(raw_event_data, dict)
                            else None
                        )
                        ev = event_name if isinstance(event_name, str) else "?"
                        log_kwargs: dict[str, Any] = {
                            "channel": channel_name,
                            "event_data": raw_event_data,
                        }
                        if peer:
                            log_kwargs["device"] = peer
                        # Open infra.event scope so this log line + the downstream handler
                        # log lines (gateway connected/disconnected, device pair/unpair,
                        # device connect/disconnect) carry the traffic_class chip in the UI.
                        with log_scope(
                            traffic_class=TRAFFIC_CLASS_INFRA_EVENT,
                            traffic_subclass=ev,
                        ):
                            event_log = (
                                log.fineinfo
                                if ev in _FINEINFO_CHANNEL_EVENTS
                                else log.info
                            )
                            event_log(
                                f"{LOG_IN} Channel event — {ev}",
                                **log_kwargs,
                            )
                            if self._on_event and isinstance(event_name, str):
                                # §5.4 — event names are no longer channel-scoped
                                # (channel.status/channel.pairing), so tell the handler
                                # which channel emitted it. The manager is authoritative
                                # for the connection's name; copy so the logged dict above
                                # is left untouched.
                                dispatch_data = (
                                    {**raw_event_data, "channel": channel_name}
                                    if isinstance(raw_event_data, dict)
                                    else raw_event_data
                                )
                                try:
                                    await self._on_event(event_name, dispatch_data)
                                except Exception as exc:
                                    log.error(
                                        f"❌ on_event handler error — ({channel_name})",
                                        error=str(exc),
                                        exc_info=True,
                                    )
                    case _:
                        with log_scope(
                            traffic_class=TRAFFIC_CLASS_INFRA_TRANSPORT,
                            traffic_subclass="unknown_method",
                        ):
                            log.warning(
                                f"⚠️ Unknown method from channel ({channel_name})",
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
            with log_scope(
                traffic_class=TRAFFIC_CLASS_INFRA_TRANSPORT,
                traffic_subclass="connection_closed",
            ):
                log.warning(f"⚠️ Channel ({channel_name}) connection closed")
        except Exception as exc:
            with log_scope(
                traffic_class=TRAFFIC_CLASS_INFRA_TRANSPORT,
                traffic_subclass="connection_error",
            ):
                log.error(
                    f"❌ Channel ({channel_name}) connection error",
                    error=str(exc),
                )
        finally:
            if channel_name and channel_name in self._channels:
                if self._channels[channel_name].ws is ws:
                    del self._channels[channel_name]
                    with log_scope(
                        traffic_class=TRAFFIC_CLASS_INFRA_TRANSPORT,
                        traffic_subclass="disconnect",
                    ):
                        log.info(f"🔌 Channel ({channel_name}) disconnected")

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

    def _persist_descriptor(self, channel_name: str, params: dict[str, Any]) -> None:
        """Persist a plugin's declared config schema + capabilities (§5.1/§5.2)."""
        from ..domain.channel_descriptor import ChannelDescriptor, save_channel_descriptor

        save_channel_descriptor(
            self._ctx.workspace_path,
            ChannelDescriptor(
                channel=channel_name,
                version=str(params.get("version", "")),
                config_schema=params.get("config_schema"),
                capabilities=params.get("capabilities"),
            ),
        )

    async def _push_config(self, channel_name: str) -> None:
        from ..domain.channel_secret_store import resolve_channel_secrets

        cfg = load_channel_config(self._ctx.workspace_path, channel_name)
        payload = dict(cfg.config) if cfg else {}
        if channel_name == MANDATORY_CHANNEL_NAME:
            payload.setdefault("gateway_url", self._ctx.config.gateway_url)
            payload.setdefault("device_id", self._ctx.config.device_id)
            payload.setdefault("ping_interval", DEFAULT_PING_INTERVAL_SECONDS)
        # §5.6 — swap any secret markers for real keyring values right before the push,
        # so the plugin receives usable config while the DB keeps only markers.
        payload = resolve_channel_secrets(self._ctx.workspace_path, channel_name, payload)
        # Always send channel.configure — even with an empty payload. The plugin
        # transport only calls on_start() from the configure handler, so a channel
        # with no config (e.g. whatsapp in P1) would otherwise never start.
        await self.configure_channel(channel_name, payload)

    # ------------------------------------------------------------------
    # Outbound API (Hiro → plugin)
    # ------------------------------------------------------------------

    async def send_to_channel(
        self, channel_name: str, message: dict[str, Any]
    ) -> None:
        ch = self._channels.get(channel_name)
        if ch is None:
            with log_scope(
                traffic_class=TRAFFIC_CLASS_INFRA_TRANSPORT,
                traffic_subclass="not_connected",
            ):
                log.warning(
                    f"⚠️ {LOG_OUT} Cannot send to ({channel_name}) — not connected"
                )
            return
        await ch.ws.send(rpc.build_notification(METHOD_SEND, message))
        routing = message.get("routing", {}) if isinstance(message, dict) else {}
        msg_id = routing.get("id", "-")
        recipient_id = routing.get("recipient_id", "")
        device = self._device_label(recipient_id) if recipient_id else "unknown"
        try:
            um = UnifiedMessage.model_validate(message)
            sd, smid, smeth, stpv, stcl, stsub = unified_message_log_scope(um, direction="outbound")
            with log_scope(
                device_id=sd,
                msg_id=smid,
                method=smeth,
                text_preview=stpv,
                traffic_class=stcl,
                traffic_subclass=stsub,
            ):
                # Stream chunks are per-chunk noise — log once at the
                # owning ``STREAM_SEND`` layer (single completion line).
                sent_log = (
                    log.fineinfo
                    if um.message_type == MESSAGE_TYPE_STREAM
                    else log.info
                )
                sent_log(
                    f"{LOG_OUT} Sent — ({channel_name}) · {device} · {comm_kind(um)}",
                    **comm_extras(um),
                )
        except Exception:
            log.info(
                f"{LOG_OUT} Sent — ({channel_name}) · {device}",
                msg_id=msg_id,
            )

    async def broadcast(self, message: dict[str, Any]) -> None:
        for ch in list(self._channels.values()):
            try:
                await ch.ws.send(rpc.build_notification(METHOD_SEND, message))
            except Exception as exc:
                log.warning(
                    f"⚠️ {LOG_OUT} Broadcast failed to ({ch.name})",
                    error=str(exc),
                )

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
            with log_scope(
                traffic_class=TRAFFIC_CLASS_INFRA_TRANSPORT,
                traffic_subclass="not_connected",
            ):
                log.warning(
                    f"⚠️ {LOG_OUT} Cannot send event to ({channel_name}) — not connected"
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

    def get_child_processes(self) -> list[tuple[str, subprocess.Popen]]:
        """Return (channel_name, Popen) pairs for all spawned channel plugins."""
        return list(self._subprocesses.items())
