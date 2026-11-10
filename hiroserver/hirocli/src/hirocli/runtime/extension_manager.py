"""ExtensionManager — the workspace's extension socket.

Extensions are programs that run on their own (HomeHiro first) and connect here,
unlike channel plugins, which the core starts itself and trusts (channel_manager.py).
So every connection signs in first (frames in hiro_channel_sdk.constants):

  1. the core sends a challenge nonce;
  2. the extension answers ``pair`` (first time: the admin's pairing code + its
     public key) or ``auth`` (its extension id), both with the nonce signed by its
     own key;
  3. the core checks the code / the stored public key and the signature, then
     sends ``welcome`` — or ``denied`` and closes.

After that both sides exchange UnifiedMessage frames in the device language:
requests (answered through the shared RequestHandler, limited to the methods open
to extensions), responses, and events. Extension traffic is not chat: it doesn't
go through CommunicationManager, isn't stored and doesn't reach the agent.

One socket per workspace serves every extension; they are told apart by key.
"""

from __future__ import annotations

import asyncio
import hmac
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

import websockets
from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

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
    METHOD_EXTENSION_INFO,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_RESPONSE,
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
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.keys import load_public_key_b64
from hiro_commons.log import Logger
from hiro_commons.nonces import generate_nonce
from hiro_commons.signing import verify_signature

from ..domain.extensions import (
    PairedExtension,
    add_paired_extension,
    clear_extension_pairing,
    get_paired_extension,
    load_extension_pairing,
    touch_paired_extension,
)
from .request_handler import CALLER_EXTENSION, RequestHandler

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("EXTENSIONS")

# After this many wrong pairing codes the current code is dropped; the admin must
# show a new one. Codes are short, so this keeps guessing pointless.
_MAX_WRONG_CODES = 5

EventHandler = Callable[[str, str, dict[str, Any]], Awaitable[None]]


@dataclass
class _Connection:
    extension_id: str
    name: str
    info: dict[str, Any]
    ws: ServerConnection
    connected_at: datetime
    remote: str


class _Denied(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.message = message


class ExtensionManager:
    """Signs extensions in and carries requests, responses and events both ways."""

    def __init__(self, ctx: ServerContext, request_handler: RequestHandler) -> None:
        self._ctx = ctx
        self._request_handler = request_handler
        self._host = ctx.config.extension_host
        self._port = ctx.config.effective_extension_port()
        self._connections: dict[str, _Connection] = {}
        self._pending: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}
        self._event_handlers: dict[str, EventHandler] = {}
        self._wrong_codes = 0
        self._listening = False
        self._listen_error: str | None = None

    # ------------------------------------------------------------------
    # Main coroutine
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Serve the extension socket until the server stops.

        A bind failure (port taken, address not on this machine) is logged and
        shown on the admin's Extensions page; it never stops the rest of the core.
        """
        try:
            # max_size: an AI ask carries up to 60 pictures as base64 (Phase 7a); the 1 MiB default is too small.
            async with websockets.serve(
                self._handle_connection, self._host, self._port, max_size=EXTENSION_MAX_MESSAGE_BYTES
            ):
                self._listening = True
                log.info(f"✅ Extension socket listening at ws://{self._host}:{self._port}")
                await self._ctx.stop_event.wait()
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

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Live connections by extension id."""
        return {
            eid: {
                "name": conn.name,
                "info": dict(conn.info),
                "connected_at": conn.connected_at.isoformat().replace("+00:00", "Z"),
                "remote": conn.remote,
            }
            for eid, conn in self._connections.items()
        }

    def register_event_handler(self, event_type: str, handler: EventHandler) -> None:
        """Call ``handler(extension_id, event_type, data)`` for that event type (Phase 5 on)."""
        self._event_handlers[event_type] = handler

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
            remote=remote,
            extension_id=conn.extension_id,
        )
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
            if found is None:
                raise _Denied(EXTENSION_DENIED_NOT_PAIRED, "unknown extension; pair it again")
            if not _signature_ok(found.public_key, nonce, signature):
                raise _Denied(EXTENSION_DENIED_BAD_SIGNATURE, "signature doesn't match the paired key")
            await asyncio.to_thread(
                touch_paired_extension, workspace, extension_id, info=info.model_dump(mode="json", by_alias=True)
            )
            extension = found
        else:
            raise _Denied(EXTENSION_DENIED_BAD_FRAME, f"expected pair or auth, got {kind!r}")

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
        workspace = self._ctx.workspace_path
        code = frame.get("code")
        public_key = frame.get("public_key")
        if not isinstance(code, str) or not isinstance(public_key, str):
            raise _Denied(EXTENSION_DENIED_BAD_FRAME, "pairing needs a code and a public key")
        session = await asyncio.to_thread(load_extension_pairing, workspace)
        if session is None or not hmac.compare_digest(session.code, code.strip()):
            self._wrong_codes += 1
            if session is not None and self._wrong_codes >= _MAX_WRONG_CODES:
                await asyncio.to_thread(clear_extension_pairing, workspace)
                self._wrong_codes = 0
                log.warning("⚠️ Too many wrong extension pairing codes — the code was dropped")
            raise _Denied(EXTENSION_DENIED_BAD_CODE, "the pairing code is wrong or has expired")
        try:
            load_public_key_b64(public_key)
        except ValueError as exc:
            raise _Denied(EXTENSION_DENIED_BAD_FRAME, f"bad public key: {exc}") from exc
        if not _signature_ok(public_key, nonce, signature):
            raise _Denied(EXTENSION_DENIED_BAD_SIGNATURE, "signature doesn't match the public key")
        extension = await asyncio.to_thread(
            add_paired_extension,
            workspace,
            name=info.name,
            public_key=public_key,
            info=info.model_dump(mode="json", by_alias=True),
        )
        await asyncio.to_thread(clear_extension_pairing, workspace)  # one code, one extension
        self._wrong_codes = 0
        log.info(f"✅ Extension paired — {info.name}", extension_id=extension.extension_id)
        return extension

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
    # Frames after sign-in
    # ------------------------------------------------------------------

    async def _handle_frame(self, conn: _Connection, raw: str) -> None:
        try:
            msg = UnifiedMessage.model_validate_json(raw)
        except ValidationError as exc:
            log.warning(f"⚠️ Unreadable message from extension — {conn.name}", error=str(exc))
            return
        # The sender is who signed in, whatever the frame claims.
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
            asyncio.create_task(self._answer(conn, msg), name=f"extension-request-{msg.request_id}")
        elif msg.message_type == MESSAGE_TYPE_EVENT and msg.event is not None:
            log.info(f"⬇️ Extension event — {conn.name} · {msg.event.type}", extension_id=conn.extension_id)
            handler = self._event_handlers.get(msg.event.type)
            if handler is not None:
                asyncio.create_task(
                    self._run_event_handler(handler, conn, msg.event.type, msg.event.data),
                    name=f"extension-event-{msg.event.type}",
                )
        else:
            log.warning(
                f"⚠️ Ignored a message from extension — {conn.name} · {msg.message_type}",
                extension_id=conn.extension_id,
            )

    async def _answer(self, conn: _Connection, msg: UnifiedMessage) -> None:
        parsed = parse_request(msg)
        method = parsed[0] if parsed else "<unreadable>"
        log.info(f"⬇️ Extension request — {conn.name} · {method}", extension_id=conn.extension_id)
        send = partial(self._send_to, conn)
        try:
            response = await self._request_handler.handle(msg, emit_outbound=send, caller=CALLER_EXTENSION)
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
