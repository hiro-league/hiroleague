"""ExtensionManager — the one extension manager: every program that plugs into the core on its machine.

An extension is a channel plugin (WhatsApp, devices, echo: the core starts it and it relays other people's chat) or
an app (HomeHiro...: it starts itself). All of them connect to one socket and sign in the same way (frames in
hiro_channel_sdk.constants):

  1. the core sends a challenge nonce;
  2. the extension answers ``pair`` (first time: a pairing code + its public key) or ``auth`` (its extension id),
     both with the nonce signed by its own key;
  3. the core checks the code / the stored public key and the signature, then sends ``welcome`` — or ``denied``
     and closes.

The kind is set once, at pairing, from who made the code: the admin's code makes an app; the code this manager made
when it started a plugin makes a channel plugin, and its row says so (domain/extensions.py): whether it may relay chat,
and that the core starts it. No frame changes it.

After that both sides exchange UnifiedMessage frames, routed by one rule — who the frame's sender is:

- the extension's own frames (on the socket's channel, ``EXTENSION_CHANNEL``): requests go to the shared
  RequestHandler as that extension's kind of caller, responses to the core's request that waits, events to the one
  event registry;
- a frame for someone else (a phone, a WhatsApp contact: its own channel) goes to chat (CommunicationManager), but
  only from an extension that may relay chat; any other extension's is kept as its own, its sender set to itself.

Outbound is the mirror: a reply to a phone or a contact goes to the extension that relays for them (by its channel's
name); a request or an event goes to the extension itself.

The four parts: sign-in, the connected extensions, routing (here) and the starter (extension_starter.py).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from logging import DEBUG
from typing import TYPE_CHECKING, Any

import websockets
from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from hiro_channel_sdk import message_story
from hiro_channel_sdk.constants import (
    CORE_REPO,
    CORE_SENDER_ID,
    EXTENSION_AUTH_TIMEOUT_SECONDS,
    EXTENSION_CHANNEL,
    EXTENSION_DENIED_BAD_CODE,
    EXTENSION_DENIED_BAD_FRAME,
    EXTENSION_DENIED_BAD_SIGNATURE,
    EXTENSION_DENIED_NOT_PAIRED,
    EXTENSION_FRAME_AUTH,
    EXTENSION_FRAME_CHALLENGE,
    EXTENSION_FRAME_DENIED,
    EXTENSION_FRAME_PAIR,
    EXTENSION_FRAME_WELCOME,
    EXTENSION_MAX_MESSAGE_BYTES,
    EXTENSION_REQUEST_TIMEOUT_SECONDS,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_RESPONSE,
    MESSAGE_TYPE_STREAM,
    METHOD_EXTENSION_CONFIGURE,
    METHOD_EXTENSION_INFO,
    METHOD_EXTENSION_STATUS,
    METHOD_EXTENSION_STOP,
    METHOD_LOGS_SEND,
    WS_CLOSE_EXTENSION_DENIED,
    WS_CLOSE_EXTENSION_REMOVED,
    WS_CLOSE_EXTENSION_REPLACED,
)
from hiro_channel_sdk.extension import (
    ExtensionInfo,
    ExtensionRequestError,
    build_event,
    build_request,
    parse_request,
    parse_response,
)
from hiro_channel_sdk.log_scope_fields import (
    TRAFFIC_CLASS_INFRA_TRANSPORT,
    unified_message_log_scope,
)
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons import tasks
from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hiro_commons.constants.network import DEFAULT_LOCALHOST
from hiro_commons.constants.timing import DEFAULT_PING_INTERVAL_SECONDS
from hiro_commons.keys import load_public_key_b64
from hiro_commons.log import FINEINFO, Logger, log_scope
from hiro_commons.logging_foundation import story
from hiro_commons.nonces import generate_nonce
from hiro_commons.signing import verify_signature

from ..domain.channel_config import list_enabled_channels, load_channel_config
from ..domain.extensions import (
    KIND_APP,
    KIND_CHANNEL,
    PairedExtension,
    add_paired_extension,
    clear_extension_pairing,
    get_paired_extension,
    load_extension_pairing,
    pair_started_extension,
    touch_paired_extension,
)
from ..domain.pairing import paired_device_ids
from .comm_log import LOG_IN, LOG_OUT, comm_extras, comm_kind, routing_requests_voice_reply
from .extension_starter import ExtensionStarter
from .request_handler import CALLER_CHANNEL, CALLER_EXTENSION, RequestHandler

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("EXTENSIONS")

_QUIET_METHODS = frozenset({METHOD_LOGS_SEND})  # answered with no line of their own (see _answer)

# After this many wrong pairing codes the admin's code is dropped; the admin must
# show a new one. Codes are short, so this keeps guessing pointless.
_MAX_WRONG_CODES = 5

# How long a started extension may take to start on its settings (WhatsApp starts its bridge), and to answer a status.
_CONFIGURE_TIMEOUT_SECONDS = 60.0
_STATUS_TIMEOUT_SECONDS = 5.0
_STOP_TIMEOUT_SECONDS = 2.0

# How long the core waits for a plugin's own method (a WhatsApp send uploads a picture and may retry once).
CHANNEL_CALL_TIMEOUT_SECONDS = 45.0

# Routine relayed events — the plugin and its handler already log the transition that owns them.
_FINEINFO_EVENTS = frozenset({"gateway_disconnected", "device_connected", "device_disconnected"})

# A kind of extension -> its kind of caller (RequestHandler): a method is open to a kind only when it names it.
_CALLER_OF_KIND = {KIND_APP: CALLER_EXTENSION, KIND_CHANNEL: CALLER_CHANNEL}

EventHandler = Callable[[str, str, dict[str, Any]], Awaitable[None]]
ChatHandler = Callable[[dict[str, Any]], Awaitable[None]]


class ChannelCallError(RuntimeError):
    """A request to a channel plugin's own method that failed: not running, timed out, or refused by the plugin.

    ``reason`` is a short code (the plugin's refusal reason, or ``not_running`` / ``timeout``); the message is meant
    for people.
    """

    def __init__(self, message: str, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class _Connection:
    extension_id: str
    name: str
    kind: str
    relays_chat: bool
    started_by_core: bool
    info: dict[str, Any]
    ws: ServerConnection
    connected_at: datetime
    remote: str


@dataclass(frozen=True)
class _EventRoute:
    handler: EventHandler
    kinds: frozenset[str]


class _Denied(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.message = message


class ExtensionManager:
    """Signs every extension in, starts the ones the core runs, and carries their frames both ways."""

    def __init__(self, ctx: ServerContext, request_handler: RequestHandler) -> None:
        self._ctx = ctx
        self._request_handler = request_handler
        self._host = ctx.config.extension_host
        self._port = ctx.config.effective_extension_port()
        self._connections: dict[str, _Connection] = {}
        self._pending: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}
        self._events: dict[str, _EventRoute] = {}
        self._on_chat: ChatHandler | None = None
        # The codes this manager made for the extensions it starts, by name: each works once, for that name only.
        self._start_codes: dict[str, str] = {}
        self._wrong_codes = 0
        self._listening = False
        self._listen_error: str | None = None
        connect_host = DEFAULT_LOCALHOST if self._host in ("", "0.0.0.0", "::") else self._host  # noqa: S104 — compared, not bound
        self._starter = ExtensionStarter(ctx, f"ws://{connect_host}:{self._port}")

    def set_chat_handler(self, handler: ChatHandler) -> None:
        """Where relayed chat goes (CommunicationManager.receive); set once both exist."""
        self._on_chat = handler

    # ------------------------------------------------------------------
    # Main coroutine
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Serve the extension socket and run the extensions the core starts, until the server stops.

        A bind failure (port taken, address not on this machine) is logged and shown on the admin's Extensions page;
        it never stops the rest of the core.
        """
        try:
            # max_size: an AI ask carries up to 60 pictures as base64 (Phase 7a); the 1 MiB default is too small.
            async with websockets.serve(
                self._handle_connection, self._host, self._port, max_size=EXTENSION_MAX_MESSAGE_BYTES
            ):
                self._listening = True
                log.info(f"✅ Extension socket listening at ws://{self._host}:{self._port}")
                await self._start_enabled()
                await self._ctx.stop_event.wait()
                await self._stop_started()
        except OSError as exc:
            self._listen_error = str(exc)
            log.error(
                "❌ Extension socket couldn't listen — extensions can't connect",
                host=self._host,
                port=self._port,
                error=str(exc),
            )
            return
        finally:
            self._listening = False
        log.info("Extension socket shut down")

    # ------------------------------------------------------------------
    # What the admin and tools read
    # ------------------------------------------------------------------

    def listen_state(self) -> dict[str, Any]:
        return {
            "host": self._host,
            "port": self._port,
            "listening": self._listening,
            "error": self._listen_error,
        }

    def snapshot(self, kind: str | None = KIND_APP) -> dict[str, dict[str, Any]]:
        """The extensions of one kind connected now, by extension id: the apps by default (uses, rights, sites and
        asks are theirs); every kind with ``kind=None`` (the admin's one list)."""
        return {
            eid: {
                "name": conn.name,
                "info": dict(conn.info),
                "connected_at": conn.connected_at.isoformat().replace("+00:00", "Z"),
                "remote": conn.remote,
            }
            for eid, conn in self._connections.items()
            if kind is None or conn.kind == kind
        }

    def name_of(self, extension_id: str) -> str:
        conn = self._connections.get(extension_id)
        return conn.name if conn is not None else ""

    def get_connected_channels(self) -> list[str]:
        """The names of the channel plugins connected now."""
        return [conn.name for conn in self._connections.values() if conn.started_by_core]

    def get_channel_info(self) -> list[dict[str, str]]:
        return [
            {
                "name": conn.name,
                "version": str(conn.info.get("version") or "?"),
                "description": str(conn.info.get("description") or ""),
            }
            for conn in self._connections.values()
            if conn.started_by_core
        ]

    def get_child_processes(self) -> list[tuple[str, Any]]:
        """(name, Popen) of each extension process the core started."""
        return self._starter.processes()

    def register_event_handler(self, event_type: str, handler: EventHandler, kinds: frozenset[str]) -> None:
        """Call ``handler(extension_id, event_type, data)`` for that event, when an extension of one of ``kinds``
        sends it as itself. The one event registry: a channel's status, pairing and device events, an app's own."""
        self._events[event_type] = _EventRoute(handler, kinds)

    # ------------------------------------------------------------------
    # Talking to an extension
    # ------------------------------------------------------------------

    async def request(
        self,
        extension_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = EXTENSION_REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Ask a connected extension; returns its data or raises ExtensionRequestError."""
        conn = self._connections.get(extension_id)
        if conn is None:
            raise ExtensionRequestError("not_connected", "the extension isn't connected")
        msg = build_request(
            method, params, sender_id=CORE_SENDER_ID, direction="outbound", recipient_id=extension_id
        )
        request_id = msg.request_id or ""
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = (extension_id, fut)
        log.info(f"⬆️ Extension request — {conn.name} · {method}", extension_id=extension_id)
        try:
            await conn.ws.send(msg.model_dump_json())
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ExtensionRequestError("timeout", f"no answer to {method} in {timeout:.0f}s") from exc
        except ConnectionClosed as exc:
            raise ExtensionRequestError("not_connected", "connection closed") from exc
        finally:
            self._pending.pop(request_id, None)

    async def refresh_info(self, extension_id: str) -> dict[str, Any]:
        """Ask a connected extension for its self-description again and keep it (Phase 7a).

        The Uses page's Refresh: the extension may declare new AI uses without signing in
        again. Stored like a sign-in's info (``touch_paired_extension``), so the uses it no
        longer declares and the new ones show. Raises ExtensionRequestError.
        """
        data = await self.request(extension_id, METHOD_EXTENSION_INFO)
        try:
            info = ExtensionInfo.model_validate(data)
        except ValidationError as exc:
            raise ExtensionRequestError("bad_answer", f"unreadable extension.info answer: {exc}") from exc
        dumped = info.model_dump(mode="json", by_alias=True)
        await asyncio.to_thread(touch_paired_extension, self._ctx.workspace_path, extension_id, info=dumped)
        conn = self._connections.get(extension_id)
        if conn is not None:
            conn.info = dumped
            conn.name = info.name
        log.info(
            f"✅ Extension info read again — {info.name} {info.version}",
            uses=len(info.uses),
            extension_id=extension_id,
        )
        return dumped

    async def send_event(self, extension_id: str, event_type: str, data: dict[str, Any] | None = None) -> bool:
        conn = self._connections.get(extension_id)
        if conn is None:
            return False
        msg = build_event(event_type, data, sender_id=CORE_SENDER_ID, direction="outbound", recipient_id=extension_id)
        try:
            await conn.ws.send(msg.model_dump_json())
        except ConnectionClosed:
            return False
        return True

    async def disconnect(self, extension_id: str) -> bool:
        """Close a removed extension's connection right away."""
        conn = self._connections.get(extension_id)
        if conn is None:
            return False
        try:
            await conn.ws.close(code=WS_CLOSE_EXTENSION_REMOVED, reason="removed in the core's admin")
        except Exception as exc:  # best-effort; the read loop cleans up
            log.warning("⚠️ Couldn't close the removed extension's connection", error=str(exc))
        return True

    # -- a channel plugin, by its name ---------------------------------------

    def _channel(self, name: str) -> _Connection | None:
        return next((c for c in self._connections.values() if c.started_by_core and c.name == name), None)

    async def send_to_channel(self, channel_name: str, message: dict[str, Any]) -> None:
        """Hand a reply for someone else (a phone, a WhatsApp contact) to the channel plugin that relays for them."""
        conn = self._channel(channel_name)
        if conn is None:
            with log_scope(traffic_class=TRAFFIC_CLASS_INFRA_TRANSPORT, traffic_subclass="not_connected"):
                log.warning(f"⚠️ {LOG_OUT} Cannot send to ({channel_name}) — not connected")
            return
        await conn.ws.send(json.dumps(message))
        _log_sent(channel_name, message, self._device_label)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for conn in [c for c in self._connections.values() if c.relays_chat]:
            try:
                await conn.ws.send(json.dumps(message))
            except ConnectionClosed as exc:
                log.warning(f"⚠️ {LOG_OUT} Broadcast failed to ({conn.name})", error=str(exc))

    async def send_event_to_channel(self, channel_name: str, event: str, data: dict[str, Any]) -> None:
        """An event for a channel plugin itself (an admin action, a pairing answer for the devices channel)."""
        conn = self._channel(channel_name)
        if conn is None:
            with log_scope(traffic_class=TRAFFIC_CLASS_INFRA_TRANSPORT, traffic_subclass="not_connected"):
                log.warning(f"⚠️ {LOG_OUT} Cannot send event to ({channel_name}) — not connected")
            return
        await self.send_event(conn.extension_id, event, data)

    async def probe_channel(self, channel_name: str) -> dict[str, Any] | None:
        conn = self._channel(channel_name)
        if conn is None:
            return None
        try:
            return await self.request(conn.extension_id, METHOD_EXTENSION_STATUS, timeout=_STATUS_TIMEOUT_SECONDS)
        except ExtensionRequestError as exc:
            log.warning(f"⚠️ Channel ({channel_name}) didn't answer its status", error=exc.message)
            return None

    async def call_channel(
        self,
        channel_name: str,
        name: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = CHANNEL_CALL_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Ask a channel plugin one of its own methods (WhatsApp's send and check) and wait for its answer.

        Raises ChannelCallError: reason ``not_running`` when the plugin isn't connected, ``timeout``, or the plugin's
        own reason when it refused.
        """
        conn = self._channel(channel_name)
        if conn is None:
            raise ChannelCallError(f"The {channel_name} channel isn't running", "not_running")
        try:
            return await self.request(conn.extension_id, name, params, timeout=timeout)
        except ExtensionRequestError as exc:
            if exc.code == "not_connected":
                raise ChannelCallError(f"The {channel_name} channel disconnected", "not_running") from exc
            if exc.code == "timeout":
                raise ChannelCallError(
                    f"The {channel_name} channel didn't answer {name} in {timeout:.0f}s", "timeout"
                ) from exc
            raise ChannelCallError(exc.message, exc.code) from exc

    async def push_config(self, channel_name: str) -> None:
        """Send a running channel plugin its settings again (saved in the admin): it applies them at once."""
        conn = self._channel(channel_name)
        if conn is None:
            return
        await self._configure(conn)

    # -- starting and stopping the ones the core runs -------------------------

    async def activate(self, channel_name: str) -> None:
        """Start a configured channel plugin live. No-op if it already runs."""
        if self._starter.running(channel_name):
            log.info(f"Extension already running — {channel_name}")
            return
        cfg = await asyncio.to_thread(load_channel_config, self._ctx.workspace_path, channel_name)
        if cfg is None:
            raise ValueError(f"Channel '{channel_name}' is not configured.")
        self._starter.start(cfg, self._new_start_code(channel_name))

    async def deactivate(self, channel_name: str) -> None:
        """Stop a running channel plugin live: ``extension.stop``, then close its connection so nothing more it sends
        reaches chat, then end its process (a tree kill by its recorded pid covers a previous server's process)."""
        self._start_codes.pop(channel_name, None)
        conn = self._channel(channel_name)
        if conn is not None:
            await self._stop_connection(conn)
        self._starter.terminate(channel_name)
        log.info(f"🔌 Extension stopped — {channel_name}")

    async def _start_enabled(self) -> None:
        channels = await asyncio.to_thread(list_enabled_channels, self._ctx.workspace_path)
        if not channels:
            log.warning("No enabled channel plugins configured")
            return
        for cfg in channels:
            self._starter.start(cfg, self._new_start_code(cfg.name))

    async def _stop_started(self) -> None:
        for conn in [c for c in self._connections.values() if c.started_by_core]:
            await self._stop_connection(conn)
        self._starter.stop_all()

    async def _stop_connection(self, conn: _Connection) -> None:
        try:
            await self.request(conn.extension_id, METHOD_EXTENSION_STOP, timeout=_STOP_TIMEOUT_SECONDS)
        except ExtensionRequestError as exc:  # it may be gone already: its process is ended next
            log.debug(f"Stop not answered — {conn.name}", error=exc.message)
        try:
            await conn.ws.close()
        except ConnectionClosed as exc:
            log.debug(f"Connection already closed — {conn.name}", error=str(exc))

    def _new_start_code(self, name: str) -> str:
        code = secrets.token_urlsafe(24)
        self._start_codes[name] = code
        return code

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def _handle_connection(self, ws: ServerConnection) -> None:
        remote = _remote_label(ws)
        try:
            extension, info = await self._sign_in(ws)
        except _Denied as denied:
            log.warning(
                f"⚠️ Extension refused — {remote} · {denied.reason}",
                message=denied.message,
            )
            await _deny(ws, denied)
            return
        except (ConnectionClosed, asyncio.TimeoutError) as exc:
            log.info(f"🔌 Extension left before signing in — {remote}", error=str(exc) or type(exc).__name__)
            return

        conn = _Connection(
            extension_id=extension.extension_id,
            name=info.name,
            kind=extension.kind,
            relays_chat=extension.relays_chat,
            started_by_core=extension.started_by_core,
            # by_alias: an ExtensionUse's answer flag is "json" on the wire (Phase 7a contract).
            info=info.model_dump(mode="json", by_alias=True),
            ws=ws,
            connected_at=datetime.now(UTC),
            remote=remote,
        )
        await self._replace_previous(conn)
        self._connections[conn.extension_id] = conn
        log.info(
            f"✅ Extension connected — {conn.name} {info.version}",
            kind=conn.kind,
            remote=remote,
            extension_id=conn.extension_id,
        )
        if conn.started_by_core:
            # A plugin starts on its settings, even empty ones: sent after every sign-in.
            tasks.keep(self._configure(conn), name=f"extension-configure-{conn.name}")
        try:
            async for raw in ws:
                await self._handle_frame(conn, str(raw))
        except ConnectionClosed:
            pass
        finally:
            await self._forget_connection(conn)

    async def _sign_in(self, ws: ServerConnection) -> tuple[PairedExtension, ExtensionInfo]:
        nonce = generate_nonce()
        await ws.send(json.dumps({"type": EXTENSION_FRAME_CHALLENGE, "nonce": nonce}))
        raw = await asyncio.wait_for(ws.recv(), timeout=EXTENSION_AUTH_TIMEOUT_SECONDS)
        try:
            frame = json.loads(raw)
            info = ExtensionInfo.model_validate(frame.get("info") or {})
        except (json.JSONDecodeError, AttributeError, ValidationError) as exc:
            raise _Denied(EXTENSION_DENIED_BAD_FRAME, f"unreadable sign-in: {exc}") from exc

        signature = frame.get("signature")
        if not isinstance(signature, str):
            raise _Denied(EXTENSION_DENIED_BAD_FRAME, "no signature")
        kind = frame.get("type")
        workspace = self._ctx.workspace_path

        if kind == EXTENSION_FRAME_PAIR:
            extension = await self._pair(frame, info, nonce, signature)
        elif kind == EXTENSION_FRAME_AUTH:
            extension_id = frame.get("extension_id")
            if not isinstance(extension_id, str) or not extension_id:
                raise _Denied(EXTENSION_DENIED_BAD_FRAME, "no extension_id")
            found = await asyncio.to_thread(get_paired_extension, workspace, extension_id)
            if found is None or not found.public_key:
                raise _Denied(EXTENSION_DENIED_NOT_PAIRED, "unknown extension; pair it again")
            if not _signature_ok(found.public_key, nonce, signature):
                raise _Denied(EXTENSION_DENIED_BAD_SIGNATURE, "signature doesn't match the paired key")
            await asyncio.to_thread(
                touch_paired_extension, workspace, extension_id, info=info.model_dump(mode="json", by_alias=True)
            )
            extension = found
        else:
            raise _Denied(EXTENSION_DENIED_BAD_FRAME, f"expected pair or auth, got {kind!r}")

        if extension.started_by_core and (info.config_schema is not None or info.capabilities is not None):
            await asyncio.to_thread(self._save_descriptor, extension.name, info)

        from .. import __version__

        await ws.send(
            json.dumps(
                {
                    "type": EXTENSION_FRAME_WELCOME,
                    "extension_id": extension.extension_id,
                    "core": {
                        "name": "HiroLeague",
                        "version": __version__,
                        "workspace": self._ctx.workspace_name,
                        # Phase 7b: the admin's web port, for an extension's links into the core's admin.
                        "admin_port": self._ctx.config.admin_port,
                        "repo": CORE_REPO,  # as core.info answers
                    },
                }
            )
        )
        return extension, info

    async def _pair(
        self, frame: dict[str, Any], info: ExtensionInfo, nonce: str, signature: str
    ) -> PairedExtension:
        code = frame.get("code")
        public_key = frame.get("public_key")
        if not isinstance(code, str) or not isinstance(public_key, str):
            raise _Denied(EXTENSION_DENIED_BAD_FRAME, "pairing needs a code and a public key")
        code = code.strip()
        try:
            load_public_key_b64(public_key)
        except ValueError as exc:
            raise _Denied(EXTENSION_DENIED_BAD_FRAME, f"bad public key: {exc}") from exc
        if not _signature_ok(public_key, nonce, signature):
            raise _Denied(EXTENSION_DENIED_BAD_SIGNATURE, "signature doesn't match the public key")
        dumped = info.model_dump(mode="json", by_alias=True)

        # A code this manager made: bound to one name, it pairs that channel plugin, once.
        started_code = self._start_codes.get(info.name)
        if started_code is not None and hmac.compare_digest(started_code, code):
            self._start_codes.pop(info.name, None)
            extension = await asyncio.to_thread(
                pair_started_extension, self._ctx.workspace_path, name=info.name, public_key=public_key, info=dumped
            )
            if extension is None:
                raise _Denied(EXTENSION_DENIED_NOT_PAIRED, f"no channel named {info.name!r} to pair")
            log.info(f"✅ Extension paired — {info.name}", kind=extension.kind, extension_id=extension.extension_id)
            return extension

        # Else the admin's code: it pairs an app.
        workspace = self._ctx.workspace_path
        session = await asyncio.to_thread(load_extension_pairing, workspace)
        if session is None or not hmac.compare_digest(session.code, code):
            self._wrong_codes += 1
            if session is not None and self._wrong_codes >= _MAX_WRONG_CODES:
                await asyncio.to_thread(clear_extension_pairing, workspace)
                self._wrong_codes = 0
                log.warning("⚠️ Too many wrong extension pairing codes — the code was dropped")
            raise _Denied(EXTENSION_DENIED_BAD_CODE, "the pairing code is wrong or has expired")
        extension = await asyncio.to_thread(
            add_paired_extension, workspace, name=info.name, public_key=public_key, info=dumped
        )
        await asyncio.to_thread(clear_extension_pairing, workspace)  # one code, one extension
        self._wrong_codes = 0
        log.info(f"✅ Extension paired — {info.name}", kind=extension.kind, extension_id=extension.extension_id)
        return extension

    def _save_descriptor(self, name: str, info: ExtensionInfo) -> None:
        """Keep a channel plugin's settings form and link steps, so the admin and the config tools draw and check them
        even while it is stopped."""
        from ..domain.channel_descriptor import ChannelDescriptor, save_channel_descriptor

        save_channel_descriptor(
            self._ctx.workspace_path,
            ChannelDescriptor(
                channel=name,
                version=info.version,
                config_schema=info.config_schema,
                capabilities=info.capabilities,
            ),
        )

    async def _configure(self, conn: _Connection) -> None:
        """Send a started extension its settings (secrets resolved from the keyring), then it starts on them."""
        from ..domain.channel_secret_store import resolve_channel_secrets

        workspace = self._ctx.workspace_path
        cfg = await asyncio.to_thread(load_channel_config, workspace, conn.name)
        payload = dict(cfg.config) if cfg else {}
        if conn.name == MANDATORY_CHANNEL_NAME:
            # Always the config's address, not a stored one: the built-in gateway's port changes with the workspace.
            payload["gateway_url"] = self._ctx.config.gateway_connect_url()
            payload.setdefault("device_id", self._ctx.config.device_id)
            payload.setdefault("ping_interval", DEFAULT_PING_INTERVAL_SECONDS)
        # Secret markers swapped for the keyring's values right before sending: the row keeps only markers.
        payload = await asyncio.to_thread(resolve_channel_secrets, workspace, conn.name, payload)
        try:
            await self.request(
                conn.extension_id, METHOD_EXTENSION_CONFIGURE, {"config": payload}, timeout=_CONFIGURE_TIMEOUT_SECONDS
            )
        except ExtensionRequestError as exc:
            log.warning(f"⚠️ Extension didn't take its settings — {conn.name}", error=exc.message, code=exc.code)

    async def _replace_previous(self, conn: _Connection) -> None:
        # The same extension connecting twice (e.g. a restart race): the newer wins.
        prev = self._connections.get(conn.extension_id)
        if prev is None or prev.ws is conn.ws:
            return
        log.warning(f"⚠️ Extension reconnected — closing its older connection · {conn.name}")
        try:
            await prev.ws.close(code=WS_CLOSE_EXTENSION_REPLACED, reason="replaced by a newer connection")
        except Exception as exc:
            log.warning("⚠️ Couldn't close the older extension connection", error=str(exc))

    async def _forget_connection(self, conn: _Connection) -> None:
        current = self._connections.get(conn.extension_id)
        if current is not None and current.ws is conn.ws:
            del self._connections[conn.extension_id]
            for request_id, (eid, fut) in list(self._pending.items()):
                if eid == conn.extension_id and not fut.done():
                    fut.set_exception(ExtensionRequestError("not_connected", "connection closed"))
                    self._pending.pop(request_id, None)
        try:
            await asyncio.to_thread(touch_paired_extension, self._ctx.workspace_path, conn.extension_id)
        except Exception as exc:  # last_seen is informational only
            log.warning("⚠️ Couldn't record when the extension was last seen", error=str(exc))
        log.info(f"🔌 Extension disconnected — {conn.name}", extension_id=conn.extension_id)

    # ------------------------------------------------------------------
    # Frames after sign-in: one routing rule
    # ------------------------------------------------------------------

    async def _handle_frame(self, conn: _Connection, raw: str) -> None:
        try:
            data = json.loads(raw)
            msg = UnifiedMessage.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            log.warning(f"⚠️ Unreadable message from extension — {conn.name}", error=str(exc))
            return
        if msg.routing.channel != EXTENSION_CHANNEL:
            if conn.relays_chat:
                # Someone else's frame, relayed in order: awaited here (a stream's chunks, a file's parts).
                await self._relay_in(conn, data, msg)
                return
            log.warning(
                f"⚠️ Frame for someone else from an extension that may not relay chat — kept as its own · {conn.name}",
                claimed_sender=msg.routing.sender_id,
                claimed_channel=msg.routing.channel,
                extension_id=conn.extension_id,
            )
        # Its own frame: the sender is who signed in, whatever the frame claims.
        msg.routing.sender_id = conn.extension_id
        msg.routing.channel = EXTENSION_CHANNEL

        if msg.message_type == MESSAGE_TYPE_RESPONSE:
            pending = self._pending.get(msg.request_id or "")
            if pending is not None and pending[0] == conn.extension_id and not pending[1].done():
                try:
                    pending[1].set_result(parse_response(msg))
                except ExtensionRequestError as exc:
                    pending[1].set_exception(exc)
        elif msg.message_type == MESSAGE_TYPE_REQUEST:
            # Answered in its own task so a slow handler doesn't hold up other frames.
            tasks.keep(self._answer(conn, msg), name=f"extension-request-{msg.request_id}")
        elif msg.message_type == MESSAGE_TYPE_EVENT and msg.event is not None:
            self._dispatch_event(conn, msg, msg.event.type, msg.event.data)
        else:
            log.warning(
                f"⚠️ Ignored a message from extension — {conn.name} · {msg.message_type}",
                extension_id=conn.extension_id,
            )

    def _dispatch_event(self, conn: _Connection, msg: UnifiedMessage, event_type: str, data: dict[str, Any]) -> None:
        # An extension's event continues its story too; its handler's task inherits it.
        with story.begin("extension.event", parent=msg.routing.metadata, area="EXTENSIONS", line=False,
                         extension=conn.name, event=event_type):
            line = log.fineinfo if event_type in _FINEINFO_EVENTS else log.info
            line(f"⬇️ Extension event — {conn.name} · {event_type}", extension_id=conn.extension_id)
            route = self._events.get(event_type)
            if route is None:
                return
            if conn.kind not in route.kinds:
                log.warning(
                    f"⚠️ Extension event refused — {conn.name} · {event_type}: not open to a {conn.kind}",
                    extension_id=conn.extension_id,
                )
                return
            tasks.keep(
                self._run_event_handler(route.handler, conn, event_type, data),
                name=f"extension-event-{event_type}",
            )

    async def _relay_in(self, conn: _Connection, data: dict[str, Any], msg: UnifiedMessage) -> None:
        """A frame a channel plugin relays for someone else: to chat (the communication manager), as a step of the
        message's story."""
        sender_id = msg.routing.sender_id or ""
        if conn.name == MANDATORY_CHANNEL_NAME and sender_id not in paired_device_ids(self._ctx.workspace_path):
            # A device no longer paired (removed in the admin, or past its pass): the gateway cuts it off too; this
            # holds when a gateway run elsewhere doesn't.
            log.warning(f"⚠️ {LOG_IN} Refused — {sender_id or 'unknown'} is not a paired device", channel=conn.name)
            return
        device = self._device_label(sender_id) if sender_id else "unknown"
        # The resolved name rides along so downstream components can log it.
        routing_meta = data.setdefault("routing", {}).setdefault("metadata", {})
        routing_meta["device_name"] = device
        # The server receiving it is a timed step of the message's story (continued from the plugin's, in the
        # metadata); the agent's run and the replies it queues are steps under it.
        try:
            story_msg_id = unified_message_log_scope(msg, direction="inbound")[1]
        except ValueError:  # a frame of no message's story: its "Received" line still says what it was
            story_msg_id = None
        with message_story.hop("server.receive", routing_meta, story_msg_id, area="EXTENSIONS"):
            _log_received(conn.name, device, msg)
            if self._on_chat is None:
                return
            try:
                await self._on_chat(data)
            except Exception as exc:
                log.error(f"❌ {LOG_IN} chat handler error — {device}", channel=conn.name, error=str(exc), exc_info=True)

    async def _answer(self, conn: _Connection, msg: UnifiedMessage) -> None:
        parsed = parse_request(msg)
        method = parsed[0] if parsed else "<unreadable>"
        # The extension's request continues the story its frame carries (a page request, a camera check...): every line
        # the handler logs here (the AI ask, an ask passed on to another app) carries its story id, and a request the
        # core sends on (extensions.ask) carries it further (build_request).
        # An app's log lines (logs.send) come every few seconds while it logs: answered without a line of their own,
        # or the core's log would hold a line for every batch of every app's.
        quiet = method in _QUIET_METHODS
        with story.begin("extension.request", parent=msg.routing.metadata, area="EXTENSIONS",
                         level=DEBUG if quiet else FINEINFO, extension=conn.name, method=method):
            (log.debug if quiet else log.info)(f"⬇️ Extension request — {conn.name} · {method}",
                                               extension_id=conn.extension_id)
            send = partial(self._send_to, conn)
            try:
                response = await self._request_handler.handle(
                    msg, emit_outbound=send, caller=_CALLER_OF_KIND.get(conn.kind, CALLER_EXTENSION)
                )
                if response is not None:
                    await send(response)
            except ConnectionClosed:
                log.info(f"🔌 Couldn't answer extension, connection closed — {conn.name} · {method}")
            except Exception as exc:
                log.error(
                    f"❌ Extension request failed — {conn.name} · {method}",
                    error=str(exc),
                    exc_info=True,
                )

    async def _send_to(self, conn: _Connection, out: UnifiedMessage) -> None:
        await conn.ws.send(out.model_dump_json())

    async def _run_event_handler(
        self, handler: EventHandler, conn: _Connection, event_type: str, data: dict[str, Any]
    ) -> None:
        try:
            await handler(conn.extension_id, event_type, data)
        except Exception as exc:
            log.error(
                f"❌ Extension event handler failed — {conn.name} · {event_type}",
                error=str(exc),
                exc_info=True,
            )

    def _device_label(self, device_id: str) -> str:
        """A paired device's name when set, else its id (compact for narrow log views)."""
        return self._ctx.device_names.resolve(device_id)


def _log_received(channel: str, device: str, um: UnifiedMessage) -> None:
    """The line for a relayed frame coming in: who, what kind, and (for a message) whether a voice reply is asked."""
    vr_suffix = ""
    vr_extras: dict[str, Any] = {}
    if um.message_type == MESSAGE_TYPE_MESSAGE:
        vr_on = routing_requests_voice_reply(um.routing.metadata)
        vr_suffix = " · voice_reply=yes" if vr_on else " · voice_reply=no"
        vr_extras["voice_reply_requested"] = vr_on
    sd, smid, smeth, stpv, stcl, stsub = unified_message_log_scope(um, direction="inbound")
    with log_scope(device_id=sd, msg_id=smid, method=smeth, text_preview=stpv, traffic_class=stcl,
                   traffic_subclass=stsub):
        log.info(f"{LOG_IN} Received — {device} · {comm_kind(um)}{vr_suffix}", **comm_extras(um, channel=channel,
                                                                                              **vr_extras))


def _log_sent(channel: str, message: dict[str, Any], device_label: Callable[[str], str]) -> None:
    routing = message.get("routing", {}) if isinstance(message, dict) else {}
    recipient_id = routing.get("recipient_id", "")
    device = device_label(recipient_id) if recipient_id else "unknown"
    try:
        um = UnifiedMessage.model_validate(message)
    except ValidationError:
        log.info(f"{LOG_OUT} Sent — ({channel}) · {device}", msg_id=routing.get("id", "-"))
        return
    sd, smid, smeth, stpv, stcl, stsub = unified_message_log_scope(um, direction="outbound")
    with log_scope(device_id=sd, msg_id=smid, method=smeth, text_preview=stpv, traffic_class=stcl,
                   traffic_subclass=stsub):
        # Stream chunks are per-chunk noise: logged once at the owning STREAM_SEND layer.
        sent = log.fineinfo if um.message_type == MESSAGE_TYPE_STREAM else log.info
        sent(f"{LOG_OUT} Sent — ({channel}) · {device} · {comm_kind(um)}", **comm_extras(um))


def _signature_ok(public_key_b64: str, nonce: str, signature: str) -> bool:
    try:
        key = load_public_key_b64(public_key_b64)
        return verify_signature(key, bytes.fromhex(nonce), signature)
    except ValueError:
        return False


def _remote_label(ws: ServerConnection) -> str:
    addr = getattr(ws, "remote_address", None)
    if isinstance(addr, tuple) and len(addr) >= 2:
        return f"{addr[0]}:{addr[1]}"
    return str(addr or "?")


async def _deny(ws: ServerConnection, denied: _Denied) -> None:
    try:
        await ws.send(json.dumps({"type": EXTENSION_FRAME_DENIED, "reason": denied.reason, "message": denied.message}))
        await ws.close(code=WS_CLOSE_EXTENSION_DENIED, reason=denied.reason)
    except ConnectionClosed:
        pass
