"""Extension contract — a program that runs on its own (HomeHiro first) and connects
to the HiroLeague core: it pairs once, signs in on every connection, then exchanges
requests, responses and events with the core.

A channel plugin (transport.py) is started by the core and trusted. An extension
is not: it pairs with a one-time code from the core's admin (sending its own public
key) and signs the core's challenge each time it connects. The frames are listed in
constants.py ("Extensions").

Usage::

    client = ExtensionClient(
        url="ws://127.0.0.1:18082",
        info=ExtensionInfo(name="home", version="1.2.0"),
        credentials=ExtensionCredentials(Path("data/hiroleague")),
    )
    task = asyncio.create_task(client.run())
    client.pair("123456")                # once, from the extension's settings
    core = await client.request("core.info")

The client answers ``extension.info`` itself. It never raises out of ``run()`` for
connection problems: it reports them through ``status`` / ``on_status`` and retries
with growing delays, so the extension keeps working when the core is down.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, Field, ValidationError
from websockets.exceptions import ConnectionClosed, InvalidURI

from hiro_commons.keys import generate_private_key, load_private_key_pem, private_key_to_pem, public_key_to_b64
from hiro_commons.log import Logger
from hiro_commons.signing import sign_nonce

from .constants import (
    CONTENT_TYPE_JSON,
    EXTENSION_AUTH_TIMEOUT_SECONDS,
    EXTENSION_CHANNEL,
    EXTENSION_DENIED_BAD_CODE,
    EXTENSION_DENIED_BAD_FRAME,
    EXTENSION_FRAME_AUTH,
    EXTENSION_FRAME_CHALLENGE,
    EXTENSION_FRAME_DENIED,
    EXTENSION_FRAME_PAIR,
    EXTENSION_FRAME_WELCOME,
    EXTENSION_MAX_MESSAGE_BYTES,
    EXTENSION_REQUEST_TIMEOUT_SECONDS,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_RESPONSE,
    METHOD_EXTENSION_INFO,
    METHOD_EXTENSIONS_ASK,
    RECONNECT_BACKOFF_BASE,
    RECONNECT_BACKOFF_MAX,
)
from .models import ContentItem, EventPayload, MessageRouting, UnifiedMessage
from .access import ExtensionFeature, ExtensionRight

log = Logger.get("EXTENSION")

# Client status values (``ExtensionClient.status``).
STATUS_NO_ADDRESS = "no_address"      # no core address set yet
STATUS_NOT_PAIRED = "not_paired"      # waiting for a pairing code
STATUS_CONNECTING = "connecting"      # connecting / signing in
STATUS_CONNECTED = "connected"        # signed in; requests and events flow
STATUS_DISCONNECTED = "disconnected"  # lost or couldn't reach the core; retrying
STATUS_STOPPED = "stopped"

_KEY_FILENAME = "extension_key.pem"
_IDENTITY_FILENAME = "extension_identity.json"


# ---------------------------------------------------------------------------
# What an extension says about itself
# ---------------------------------------------------------------------------


class ExtensionOffers(BaseModel):
    """What the extension offers the core: the hero contract's slots.

    Still empty: extensions declaring what they know and can do waits until Home
    is mature enough (the plan's Later). For now the core asks every extension
    the same ``extension.state`` (Phase 5). Each entry will be a small dict
    naming the request method or event and describing it.
    """

    knows: list[dict[str, Any]] = Field(default_factory=list)   # questions it answers
    can_do: list[dict[str, Any]] = Field(default_factory=list)  # actions it takes
    tells: list[dict[str, Any]] = Field(default_factory=list)   # events it sends
    shows: list[dict[str, Any]] = Field(default_factory=list)   # pages it has


class ExtensionUse(BaseModel):
    """One thing the extension asks the core's AI for (Phase 7a): the core's admin points
    each use at an AI profile. ``pictures`` is the most pictures one ask carries (0 = none).
    ``folder``: the ask names a folder on the core's machine for the tool to read (a code review); only a
    Claude Code or Codex profile can answer it, and only inside the folders the admin allowed this extension."""

    id: str
    name: str
    pictures: int = 0
    sound: bool = False
    json_answer: bool = Field(default=True, alias="json")
    folder: bool = False

    model_config = {"populate_by_name": True}


class ExtensionVoiceUse(BaseModel):
    """One thing the extension asks the core to say aloud (Phase 7b): the core's admin points each voice use
    at a voice profile (``voice.uses["<extension>:<id>"]``)."""

    id: str
    name: str


class ExtensionInfo(BaseModel):
    """Self-description an extension sends when it signs in (and answers to extension.info)."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    offers: ExtensionOffers = Field(default_factory=ExtensionOffers)
    # What it asks the core's AI for (Phase 7a); the core keeps the last list it was given.
    uses: list[ExtensionUse] = Field(default_factory=list)
    # What it asks the core to say aloud (Phase 7b: voice.speak), each pointed at a voice profile.
    voice_uses: list[ExtensionVoiceUse] = Field(default_factory=list)
    # The git repo it is built from, by name ("homehiro": ~/homehiro.git on the server); "" = not said. The code reports
    # keep a report for each extension's repo (extensions.list).
    repo: str = ""
    # Phase 9a: its features and the rights in each; the core's admin grants them per role (access.py).
    features: list[ExtensionFeature] = Field(default_factory=list)


class ExtensionRequestError(Exception):
    """A request was answered with an error, timed out, or couldn't be sent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Message builders — shared by the client and the core
# ---------------------------------------------------------------------------


def build_request(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    sender_id: str,
    direction: str,
    recipient_id: str | None = None,
) -> UnifiedMessage:
    """A request in the device language: JSON body ``{"method", "params"}``."""
    return UnifiedMessage(
        message_type=MESSAGE_TYPE_REQUEST,
        request_id=uuid4().hex,
        routing=MessageRouting(
            channel=EXTENSION_CHANNEL,
            direction=direction,
            sender_id=sender_id,
            recipient_id=recipient_id,
        ),
        content=[
            ContentItem(
                content_type=CONTENT_TYPE_JSON,
                body=json.dumps({"method": method, "params": params or {}}),
            )
        ],
    )


def build_response(
    request: UnifiedMessage,
    *,
    sender_id: str,
    direction: str,
    data: dict[str, Any] | None = None,
    error: tuple[str, str] | None = None,
) -> UnifiedMessage:
    """The answer to ``request``: ``{"status": "ok", "data"}`` or ``{"status": "error", "error"}``."""
    if error is None:
        body: dict[str, Any] = {"status": "ok", "data": data or {}}
    else:
        body = {"status": "error", "error": {"code": error[0], "message": error[1]}}
    return UnifiedMessage(
        message_type=MESSAGE_TYPE_RESPONSE,
        request_id=request.request_id,
        routing=MessageRouting(
            channel=EXTENSION_CHANNEL,
            direction=direction,
            sender_id=sender_id,
            recipient_id=request.routing.sender_id,
        ),
        content=[ContentItem(content_type=CONTENT_TYPE_JSON, body=json.dumps(body))],
    )


def build_event(
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    sender_id: str,
    direction: str,
    recipient_id: str | None = None,
) -> UnifiedMessage:
    """A fire-and-forget event."""
    return UnifiedMessage(
        message_type=MESSAGE_TYPE_EVENT,
        routing=MessageRouting(
            channel=EXTENSION_CHANNEL,
            direction=direction,
            sender_id=sender_id,
            recipient_id=recipient_id,
        ),
        event=EventPayload(type=event_type, data=data or {}),
    )


def parse_request(msg: UnifiedMessage) -> tuple[str, dict[str, Any]] | None:
    """``(method, params)`` from a request's JSON body, or None when unreadable."""
    for item in msg.content:
        if item.content_type != CONTENT_TYPE_JSON:
            continue
        try:
            body = json.loads(item.body)
        except json.JSONDecodeError:
            return None
        method = body.get("method") if isinstance(body, dict) else None
        params = body.get("params") or {} if isinstance(body, dict) else {}
        if isinstance(method, str) and method and isinstance(params, dict):
            return method, params
        return None
    return None


def parse_response(msg: UnifiedMessage) -> dict[str, Any]:
    """The ``data`` of an ok response; raises ExtensionRequestError for an error one."""
    for item in msg.content:
        if item.content_type != CONTENT_TYPE_JSON:
            continue
        try:
            body = json.loads(item.body)
        except json.JSONDecodeError as exc:
            raise ExtensionRequestError("invalid_response", str(exc)) from exc
        if not isinstance(body, dict):
            break
        if body.get("status") == "ok":
            data = body.get("data")
            return data if isinstance(data, dict) else {"value": data}
        err = body.get("error") or {}
        raise ExtensionRequestError(
            str(err.get("code") or "error"), str(err.get("message") or "request failed")
        )
    raise ExtensionRequestError("invalid_response", "response has no JSON body")


# ---------------------------------------------------------------------------
# The extension's own key and the id the core gave it
# ---------------------------------------------------------------------------


class ExtensionCredentials:
    """Keeps the extension's private key and its extension id in one folder.

    - ``extension_key.pem``: the Ed25519 private key (mode 0600). It never leaves
      this folder; the core only ever sees the public half.
    - ``extension_identity.json``: ``{"extension_id": "..."}``, set at pairing.

    Put the folder with the extension's own data so it is backed up with it; if
    it is lost, pair again.
    """

    def __init__(self, folder: Path) -> None:
        self._folder = Path(folder)

    @property
    def folder(self) -> Path:
        return self._folder

    def private_key(self) -> Ed25519PrivateKey:
        """Load the key, creating it on first use."""
        path = self._folder / _KEY_FILENAME
        if path.exists():
            return load_private_key_pem(path.read_bytes())
        self._folder.mkdir(parents=True, exist_ok=True)
        key = generate_private_key()
        path.write_bytes(private_key_to_pem(key))
        try:
            os.chmod(path, 0o600)
        except OSError as exc:  # e.g. a filesystem without POSIX modes
            log.warning("⚠️ Could not restrict the extension key file", path=str(path), error=str(exc))
        return key

    def extension_id(self) -> str | None:
        path = self._folder / _IDENTITY_FILENAME
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("extension_id")
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            log.warning("⚠️ Extension identity file unreadable — pair again", error=str(exc))
            return None
        return value if isinstance(value, str) and value else None

    def save_extension_id(self, extension_id: str) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        (self._folder / _IDENTITY_FILENAME).write_text(
            json.dumps({"extension_id": extension_id}), encoding="utf-8"
        )

    def forget(self) -> None:
        """Drop the key and the id (removed in the core, or pairing anew)."""
        for name in (_IDENTITY_FILENAME, _KEY_FILENAME):
            try:
                (self._folder / name).unlink()
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------

RequestHandlerFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
EventHandlerFn = Callable[[str, dict[str, Any]], Awaitable[None]]
StatusCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class _Denied(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.message = message


class ExtensionClient:
    """Keeps an extension connected to the core and carries its messages."""

    def __init__(
        self,
        url: str,
        info: ExtensionInfo,
        credentials: ExtensionCredentials,
        *,
        on_status: StatusCallback | None = None,
    ) -> None:
        self._url = url.strip()
        self._info = info
        self._credentials = credentials
        self._on_status = on_status
        self._request_handlers: dict[str, RequestHandlerFn] = {}
        self._event_handlers: dict[str, EventHandlerFn] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._ws: Any = None
        self._pairing_code: str | None = None
        self._stopping = False
        self._wake = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        self._status = STATUS_STOPPED
        self._detail: dict[str, Any] = {}
        self._core: dict[str, Any] = {}

    # -- what the extension sets up ------------------------------------------

    def update_info(self, info: ExtensionInfo) -> None:
        """Change what the extension declares (Phase 8: its site's address, its offered sign-ins).

        Sent at the next sign-in, and answered to the core's ``extension.info`` from now on; reconnect
        for the core to see it at once.
        """
        self._info = info

    def register_request(self, method: str, handler: RequestHandlerFn) -> None:
        """Answer the core's ``method`` requests with ``handler(params) -> data``."""
        self._request_handlers[method] = handler

    def on_event(self, event_type: str, handler: EventHandlerFn) -> None:
        """Call ``handler(event_type, data)`` for the core's ``event_type`` events."""
        self._event_handlers[event_type] = handler

    # -- state -----------------------------------------------------------------

    @property
    def status(self) -> str:
        return self._status

    @property
    def status_detail(self) -> dict[str, Any]:
        """Extra facts for the status: ``error``, ``core`` (name/version), ``extension_id``."""
        return dict(self._detail)

    @property
    def url(self) -> str:
        return self._url

    @property
    def connected(self) -> bool:
        return self._status == STATUS_CONNECTED and self._ws is not None

    # -- control ---------------------------------------------------------------

    def set_url(self, url: str) -> None:
        """Point at another core address; reconnects there."""
        self._url = url.strip()
        self._drop_connection()

    def pair(self, code: str) -> None:
        """Pair with a code from the core's admin. Replaces any earlier pairing."""
        self._credentials.forget()  # a fresh key for the new pairing
        self._pairing_code = code.strip()
        self._drop_connection()

    def forget(self) -> None:
        """Unpair on this side: drop the key and id, disconnect."""
        self._credentials.forget()
        self._pairing_code = None
        self._drop_connection()

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        ws = self._ws
        if ws is not None:
            try:
                await ws.close()
            except Exception as exc:  # best-effort teardown
                log.warning("⚠️ Extension close failed", error=str(exc))

    async def run(self) -> None:
        """Stay connected until ``stop()``; never raises for connection problems."""
        backoff = RECONNECT_BACKOFF_BASE
        while not self._stopping:
            self._wake.clear()
            if not self._url:
                await self._set_status(STATUS_NO_ADDRESS, {})
                await self._wake.wait()
                continue
            if self._pairing_code is None and self._credentials.extension_id() is None:
                # Keep the reason from a refusal ("the code was wrong") while waiting.
                detail = self._detail if self._status == STATUS_NOT_PAIRED else {}
                await self._set_status(STATUS_NOT_PAIRED, detail)
                await self._wake.wait()
                continue

            welcomed = False
            try:
                await self._set_status(STATUS_CONNECTING, {})
                welcomed = await self._session()
            except _Denied as denied:
                await self._on_denied(denied)
                if self._status == STATUS_NOT_PAIRED:
                    continue  # waits for a new code on the next turn
            except (OSError, ConnectionClosed, InvalidURI, asyncio.TimeoutError, ValueError) as exc:
                log.info("🔌 Extension couldn't stay connected to the core", url=self._url, error=str(exc))
                await self._set_status(STATUS_DISCONNECTED, {"error": str(exc) or type(exc).__name__})
            except Exception as exc:  # never let a bug end the extension's own app
                log.error("❌ Extension connection failed", url=self._url, error=str(exc), exc_info=True)
                await self._set_status(STATUS_DISCONNECTED, {"error": str(exc)})

            if self._stopping:
                break
            if welcomed:
                backoff = RECONNECT_BACKOFF_BASE
                if self._status == STATUS_CONNECTED:
                    await self._set_status(STATUS_DISCONNECTED, {"error": "connection closed"})
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)
        await self._set_status(STATUS_STOPPED, {})

    # -- talking to the core ----------------------------------------------------

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = EXTENSION_REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Ask the core; returns the response data or raises ExtensionRequestError."""
        ws = self._ws
        if ws is None or self._status != STATUS_CONNECTED:
            raise ExtensionRequestError("not_connected", "not connected to the core")
        msg = build_request(method, params, sender_id=self._sender_id(), direction="inbound")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[msg.request_id or ""] = fut
        try:
            await ws.send(msg.model_dump_json())
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ExtensionRequestError("timeout", f"no answer to {method} in {timeout:.0f}s") from exc
        except ConnectionClosed as exc:
            raise ExtensionRequestError("not_connected", "connection closed") from exc
        finally:
            self._pending.pop(msg.request_id or "", None)

    async def ask(
        self,
        to: str,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = EXTENSION_REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Phase 9b: ask another extension (by its name) through the core; it must offer ``method`` in its
        ``offers.knows`` / ``offers.can_do``. Returns its answer or raises ExtensionRequestError (not_connected,
        not_offered, timeout, or the asked extension's own error)."""
        # The core waits up to `timeout` for the asked extension; this side waits a little longer for the core.
        return await self.request(
            METHOD_EXTENSIONS_ASK,
            {"to": to, "method": method, "params": params or {}, "timeout": timeout},
            timeout=timeout + 5.0,
        )

    async def send_event(self, event_type: str, data: dict[str, Any] | None = None) -> bool:
        """Tell the core something; False when not connected (events aren't queued)."""
        ws = self._ws
        if ws is None or self._status != STATUS_CONNECTED:
            return False
        msg = build_event(event_type, data, sender_id=self._sender_id(), direction="inbound")
        try:
            await ws.send(msg.model_dump_json())
        except ConnectionClosed:
            return False
        return True

    # -- internals ---------------------------------------------------------------

    def _sender_id(self) -> str:
        return self._credentials.extension_id() or self._info.name

    def _drop_connection(self) -> None:
        # Wake the run loop and close the socket so it reconnects with the new settings.
        self._wake.set()
        ws = self._ws
        if ws is not None:
            self._spawn(self._close_quietly(ws))

    async def _close_quietly(self, ws: Any) -> None:
        try:
            await ws.close()
        except Exception as exc:
            log.warning("⚠️ Extension close failed", error=str(exc))

    def _spawn(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _set_status(self, status: str, detail: dict[str, Any]) -> None:
        self._status = status
        self._detail = detail
        if self._on_status is None:
            return
        try:
            result = self._on_status(status, dict(detail))
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            log.error("❌ Extension status callback failed", status=status, error=str(exc), exc_info=True)

    async def _on_denied(self, denied: _Denied) -> None:
        log.warning("⚠️ The core refused the extension", reason=denied.reason, message=denied.message)
        if denied.reason == EXTENSION_DENIED_BAD_CODE:
            self._pairing_code = None
            self._credentials.forget()
            message = "The pairing code was wrong or has expired. Get a new one from the core's admin."
        elif denied.reason == EXTENSION_DENIED_BAD_FRAME:
            # Not the core (wrong address?) — retry with the usual delays, keep any code.
            await self._set_status(STATUS_DISCONNECTED, {"error": denied.message})
            return
        else:
            # not_paired / bad_signature: the core doesn't know this key (e.g. removed in its admin).
            self._pairing_code = None
            self._credentials.forget()
            message = "The core doesn't know this extension any more. Pair it again."
        await self._set_status(STATUS_NOT_PAIRED, {"error": message})

    async def _session(self) -> bool:
        """One connection: sign in, then serve frames. True once welcomed."""
        key = self._credentials.private_key()
        # max_size: an AI ask can carry up to 60 pictures as base64 (Phase 7a); the default 1 MiB is far too small.
        async with websockets.connect(
            self._url, open_timeout=EXTENSION_AUTH_TIMEOUT_SECONDS, max_size=EXTENSION_MAX_MESSAGE_BYTES
        ) as ws:
            challenge = await self._recv_json(ws)
            nonce = challenge.get("nonce")
            if challenge.get("type") != EXTENSION_FRAME_CHALLENGE or not isinstance(nonce, str):
                raise _Denied(EXTENSION_DENIED_BAD_FRAME, "The address answered, but not like a HiroLeague core.")
            signature = sign_nonce(key, nonce)
            info = self._info.model_dump(mode="json", by_alias=True)
            code = self._pairing_code
            if code:
                frame: dict[str, Any] = {
                    "type": EXTENSION_FRAME_PAIR,
                    "code": code,
                    "public_key": public_key_to_b64(key.public_key()),
                    "signature": signature,
                    "info": info,
                }
            else:
                frame = {
                    "type": EXTENSION_FRAME_AUTH,
                    "extension_id": self._credentials.extension_id(),
                    "signature": signature,
                    "info": info,
                }
            await ws.send(json.dumps(frame))
            reply = await self._recv_json(ws)
            if reply.get("type") == EXTENSION_FRAME_DENIED:
                raise _Denied(str(reply.get("reason") or "denied"), str(reply.get("message") or ""))
            if reply.get("type") != EXTENSION_FRAME_WELCOME or not reply.get("extension_id"):
                raise _Denied(EXTENSION_DENIED_BAD_FRAME, "Unexpected answer from the core.")
            if code:
                self._credentials.save_extension_id(str(reply["extension_id"]))
                self._pairing_code = None
                log.info("✅ Extension paired with the core", extension=self._info.name)
            self._core = dict(reply.get("core") or {})
            self._ws = ws
            await self._set_status(
                STATUS_CONNECTED,
                {"core": dict(self._core), "extension_id": str(reply["extension_id"])},
            )
            log.info("✅ Extension connected to the core", extension=self._info.name, url=self._url)
            try:
                async for raw in ws:
                    await self._handle_frame(ws, str(raw))
            finally:
                self._ws = None
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(ExtensionRequestError("not_connected", "connection closed"))
            return True

    async def _recv_json(self, ws: Any) -> dict[str, Any]:
        raw = await asyncio.wait_for(ws.recv(), timeout=EXTENSION_AUTH_TIMEOUT_SECONDS)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _Denied(EXTENSION_DENIED_BAD_FRAME, "The core sent something unreadable.") from exc
        if not isinstance(data, dict):
            raise _Denied(EXTENSION_DENIED_BAD_FRAME, "The core sent something unreadable.")
        return data

    async def _handle_frame(self, ws: Any, raw: str) -> None:
        try:
            msg = UnifiedMessage.model_validate_json(raw)
        except ValidationError as exc:
            log.warning("⚠️ Unreadable message from the core", error=str(exc))
            return
        if msg.message_type == MESSAGE_TYPE_RESPONSE:
            fut = self._pending.get(msg.request_id or "")
            if fut is not None and not fut.done():
                try:
                    fut.set_result(parse_response(msg))
                except ExtensionRequestError as exc:
                    fut.set_exception(exc)
        elif msg.message_type == MESSAGE_TYPE_REQUEST:
            # Answered in its own task so a slow handler doesn't hold up other frames.
            self._spawn(self._answer(ws, msg))
        elif msg.message_type == MESSAGE_TYPE_EVENT and msg.event is not None:
            handler = self._event_handlers.get(msg.event.type)
            if handler is not None:
                self._spawn(self._run_event_handler(handler, msg.event.type, msg.event.data))
        else:
            log.warning("⚠️ Ignored a message from the core", message_type=msg.message_type)

    async def _answer(self, ws: Any, msg: UnifiedMessage) -> None:
        parsed = parse_request(msg)
        sender = self._sender_id()
        if parsed is None:
            reply = build_response(
                msg, sender_id=sender, direction="inbound", error=("invalid_request", "unreadable request")
            )
        else:
            method, params = parsed
            reply = await self._call_handler(msg, method, params, sender)
        try:
            await ws.send(reply.model_dump_json())
        except ConnectionClosed:
            log.info("🔌 Couldn't answer the core: connection closed")

    async def _call_handler(
        self, msg: UnifiedMessage, method: str, params: dict[str, Any], sender: str
    ) -> UnifiedMessage:
        if method == METHOD_EXTENSION_INFO:
            # The whole self-description, uses included: the core's Uses page Refresh asks this (Phase 7a).
            data = self._info.model_dump(mode="json", by_alias=True)
            return build_response(msg, sender_id=sender, direction="inbound", data=data)
        handler = self._request_handlers.get(method)
        if handler is None:
            return build_response(
                msg, sender_id=sender, direction="inbound", error=("method_not_found", f"Unknown method: {method}")
            )
        try:
            data = await handler(params)
        except ExtensionRequestError as exc:
            # Phase 8: a handler answers a contract's own error code (sign_in.finish: not_linked / failed), so the
            # core can tell people why, instead of a generic internal_error.
            log.warning(f"⚠️ Extension request refused — {method} · {exc.code}", error=exc.message)
            return build_response(msg, sender_id=sender, direction="inbound", error=(exc.code, exc.message))
        except Exception as exc:
            log.error("❌ Extension request handler failed", method=method, error=str(exc), exc_info=True)
            return build_response(msg, sender_id=sender, direction="inbound", error=("internal_error", str(exc)))
        return build_response(msg, sender_id=sender, direction="inbound", data=data)

    async def _run_event_handler(self, handler: EventHandlerFn, event_type: str, data: dict[str, Any]) -> None:
        try:
            await handler(event_type, data)
        except Exception as exc:
            log.error("❌ Extension event handler failed", event_type=event_type, error=str(exc), exc_info=True)
