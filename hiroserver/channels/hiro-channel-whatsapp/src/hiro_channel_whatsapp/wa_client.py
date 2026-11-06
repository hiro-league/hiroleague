"""Thin async wrapper around neonize's WhatsApp client.

This is the ONLY WhatsApp-aware module in the plugin: it isolates the unofficial
neonize/whatsmeow library behind a small, swappable surface (design doc §3). The
plugin talks to it via three async callbacks — ``on_qr``, ``on_status``,
``on_message`` — and never imports neonize types directly.

Phase 1 scope: connect + QR login + session persistence + surface inbound
messages. Sending is added in Phase 2; media download in Phase 6/7.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import random
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine

from google.protobuf.message import DecodeError

from hiro_commons.log import Logger

from .audio import compute_waveform

# neonize async client + event types. These load the bundled Go shared library
# (whatsmeow) at import time; that is expected and only happens in this module.
from neonize.aioze.client import NewAClient
from neonize.aioze.events import (
    ClientOutdatedEv,
    ConnectedEv,
    ConnectFailureEv,
    DisconnectedEv,
    LoggedOutEv,
    MessageEv,
    PairStatusEv,
    StreamReplacedEv,
    TemporaryBanEv,
)
from neonize.exc import SendMessageError
from neonize.proto.waCompanionReg.WAWebProtobufsCompanionReg_pb2 import DeviceProps
from neonize.utils import Jid2String, JIDToNonAD, build_jid
from neonize.utils.enum import ChatPresence, ChatPresenceMedia, Presence, ReceiptType

log = Logger.get("WHATSAPP.CLIENT")

# Device identity presented to WhatsApp at link time. It appears in the phone's
# "Linked Devices" list and in the companion registration the WA servers see.
# neonize's default is os="Neonize" (aioze/client.py connect()), a blatant
# "unofficial automation" fingerprint; present as an ordinary desktop browser
# instead so we don't advertise the library to Meta's classifiers. NOTE: device
# props are baked at pair time — changing them requires deleting session.db and
# re-scanning the QR.
_DEVICE_OS = "Chrome"
_DEVICE_PLATFORM = DeviceProps.CHROME

# Human-like timing (randomized per message) so the agent doesn't reply with
# mechanical, instant precision. Read receipt (blue ticks) lags a touch; a
# "typing…" presence is shown for a short randomized window before the reply is
# actually sent. Ranges are (min_seconds, max_seconds).
_READ_RECEIPT_DELAY_S = (0.5, 1.0)   # lag before marking an inbound message read
_TYPING_DELAY_S = (1.0, 2.0)         # how long "typing…" shows before the reply

# Reconnect backoff ceiling (base 1s, doubling). Mirrors hiro-channel-devices so a
# dropped WhatsApp socket retries without hammering the WA servers.
_RECONNECT_BACKOFF_MAX_S = 60.0

# whatsmeow's QR login: the first code is valid 60 s, each later one 20 s, and after
# the last one WhatsApp closes the linking window (about 2.5 min in all). neonize 0.5.x
# signals nothing when that happens (its login-status callback is a no-op) and its
# idle() only returns once the client is stopped, so without help the plugin would
# sit on a dead code forever (the phone says "couldn't link device"). The bridge arms
# a watchdog on every code; when no new code, pairing or connection follows within
# the code's lifetime plus a grace, it stops the client and run() opens a new window.
_QR_FIRST_CODE_S = 60.0
_QR_NEXT_CODE_S = 20.0
_QR_GRACE_S = 10.0
# How long run() waits for idle() once the client was stopped. A Stop() that lands
# while a QR window is still open leaves neonize's Go call blocked for good (seen on
# Simone, 2026-11-06), so past this run() gives up on that client (one blocked Go
# thread) and builds a new one instead of leaving the channel dead.
_STOPPED_IDLE_GRACE_S = 15.0

# WhatsApp mobile only renders a voice-note (PTT) bubble when the audio mimetype
# spells out the codec; bare "audio/ogg" (what libmagic sniffs) is dropped.
_PTT_MIMETYPE = "audio/ogg; codecs=opus"

# Async callback aliases the plugin implements.
QrCallback = Callable[[str], Awaitable[None]]
StatusCallback = Callable[[str, dict[str, Any]], Awaitable[None]]
MessageCallback = Callable[[dict[str, Any]], Awaitable[None]]


class WhatsAppBridge:
    """Owns a neonize ``NewAClient`` and forwards its events to async callbacks."""

    def __init__(
        self,
        session_db_path: str,
        *,
        on_qr: QrCallback,
        on_status: StatusCallback,
        on_message: MessageCallback,
        send_read_receipts: bool = True,
    ) -> None:
        self._session_db_path = session_db_path
        self._on_qr = on_qr
        self._on_status = on_status
        self._on_message = on_message
        self._send_read_receipts = send_read_receipts
        self._stopping = False
        self._client: NewAClient | None = None
        # True once we've had at least one successful connection. Distinguishes a
        # post-pair reconnect (emit "reconnecting") from the initial QR-cycling loop
        # (where the UI is showing a QR and a "reconnecting" status would confuse).
        self._was_connected = False
        # Background fire-and-forget tasks (delayed read receipts); referenced so
        # they are not garbage-collected mid-flight.
        self._tasks: set[asyncio.Task[None]] = set()
        # QR-window watchdog (see _QR_FIRST_CODE_S) and how many codes the current
        # client has issued (the first one lives longer).
        self._qr_watchdog: asyncio.Task[None] | None = None
        self._qr_codes_issued = 0
        # True once the current client was stopped. neonize's Go Stop() deletes the
        # client, and a later Disconnect() on it panics, so it is stopped only once.
        self._client_ended = False
        # Set together with _client_ended; run() waits on it next to idle().
        self._client_ended_event: asyncio.Event | None = None
        # The session DB is created by neonize; ensure its parent dir exists so a
        # fresh install (no prior session) can write it and trigger QR pairing.
        Path(session_db_path).parent.mkdir(parents=True, exist_ok=True)

    # -- lifecycle ---------------------------------------------------------

    def _build_client(self) -> NewAClient:
        # Pass explicit DeviceProps so we register as an ordinary browser rather
        # than neonize's default os="Neonize" fingerprint (see _DEVICE_OS note).
        props = DeviceProps(os=_DEVICE_OS, platformType=_DEVICE_PLATFORM)
        client = NewAClient(self._session_db_path, props=props)
        self._client = client
        self._client_ended = False
        self._client_ended_event = asyncio.Event()
        self._qr_codes_issued = 0
        self._register_handlers()
        return client

    async def _idle(self, client: NewAClient) -> None:
        """Wait until ``client``'s session ends: idle() returns, or the bridge
        stopped the client and idle() didn't follow within the grace."""
        ended = self._client_ended_event
        idle_task = asyncio.ensure_future(client.idle())
        ended_task = asyncio.ensure_future(ended.wait()) if ended is not None else None
        waiting = {idle_task} if ended_task is None else {idle_task, ended_task}
        try:
            done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if ended_task is not None:
                ended_task.cancel()
        if idle_task in done:
            idle_task.result()  # surface a neonize error to run()'s handler
            return
        try:
            await asyncio.wait_for(asyncio.shield(idle_task), _STOPPED_IDLE_GRACE_S)
        except asyncio.TimeoutError:
            # Leave the blocked call behind; consume its eventual result so asyncio
            # doesn't warn about an unretrieved exception.
            idle_task.add_done_callback(_consume_result)
            log.warning(
                "⚠️ WhatsApp client didn't shut down after stop — starting a new one",
                waited_s=_STOPPED_IDLE_GRACE_S,
            )

    async def _end_client(self, client: NewAClient) -> None:
        """Close the socket and stop neonize's Go session for ``client``.

        neonize 0.5.x's idle() returns only after Stop(), not after Disconnect(), so
        every path that wants run() to rebuild (stop, reconnect, logout, an expired
        QR window) ends here. Stop() also deletes the Go-side client, after which a
        Disconnect() panics, so this runs once per client.
        """
        if client is not self._client or self._client_ended:
            return
        self._client_ended = True
        self._cancel_qr_watchdog()
        if self._client_ended_event is not None:
            self._client_ended_event.set()
        try:
            await client.disconnect()
        except Exception as exc:  # best-effort teardown; Stop() below still ends it
            log.warning("⚠️ WhatsApp disconnect failed", error=str(exc))
        try:
            await client.stop()
        except Exception as exc:
            log.error("❌ WhatsApp client stop failed — channel may need a restart", error=str(exc))

    def _arm_qr_watchdog(self, client: NewAClient) -> None:
        # Called on every QR code: the window is open as long as codes keep coming.
        self._cancel_qr_watchdog()
        lifetime = _QR_FIRST_CODE_S if self._qr_codes_issued == 0 else _QR_NEXT_CODE_S
        self._qr_codes_issued += 1
        self._qr_watchdog = asyncio.ensure_future(
            self._expire_qr_window(client, lifetime + _QR_GRACE_S)
        )

    def _cancel_qr_watchdog(self) -> None:
        watchdog = self._qr_watchdog
        self._qr_watchdog = None
        if watchdog is not None and watchdog is not asyncio.current_task():
            watchdog.cancel()

    async def _expire_qr_window(self, client: NewAClient, delay_s: float) -> None:
        await asyncio.sleep(delay_s)
        if self._stopping or client is not self._client:
            return
        log.info("🔗 WhatsApp QR window closed unscanned — opening a new one")
        await self._end_client(client)

    def _schedule(self, coro: Coroutine[Any, Any, None]) -> None:
        # Fire-and-forget a coroutine, keeping a reference until it finishes so the
        # event loop doesn't drop it mid-run.
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def run(self) -> None:
        """Connect and keep the session alive, reconnecting on drop.

        whatsmeow's QR login issues a short sequence of rotating codes and then
        closes the socket if none is scanned in time. Reconnecting re-opens a
        fresh QR cycle (so the user always has a valid code) until the account is
        linked; after pairing, the same loop reconnects using the saved session.
        A fresh client is built per attempt because the Go socket is one-shot.
        """
        backoff = 1.0
        while not self._stopping:
            try:
                client = self._build_client()
                await client.connect()
                await self._enable_receipts(client)
                backoff = 1.0  # reset after a successful connect so a later drop restarts fresh
                # Not client.idle() directly: on neonize 0.5.x it can stay blocked
                # after a stop (see _STOPPED_IDLE_GRACE_S).
                await self._idle(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # external library boundary — never crash silently
                log.error("❌ WhatsApp client loop failed", error=str(exc), exc_info=True)
            if self._stopping:
                break
            # Only surface a reconnect status once we've been connected — during the
            # initial QR-cycling this same loop just refreshes the pairing code.
            if self._was_connected:
                await self._safe_status("reconnecting", {"backoff_s": round(backoff, 1)})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX_S)

    def set_send_read_receipts(self, value: bool) -> None:
        """Live-update the read-receipt policy (settings changed while running)."""
        self._send_read_receipts = value

    async def stop(self) -> None:
        self._stopping = True
        client = self._client
        if client is None:
            return
        # Stop, not just disconnect: on neonize 0.5.x only Stop() lets idle() return.
        await self._end_client(client)

    async def reconnect(self) -> None:
        """Force a re-link: end the client so run()'s loop rebuilds + reconnects
        using the saved session (no new QR)."""
        client = self._client
        if client is None:
            return
        # Stop, not just disconnect: on neonize 0.5.x only Stop() lets idle() return.
        await self._end_client(client)

    async def logout(self) -> None:
        """Unlink the account: log out on WhatsApp + clear the local session, then
        the run() loop rebuilds and issues a fresh QR to re-pair."""
        client = self._client
        if client is None or self._client_ended:
            return
        try:
            await client.logout()  # unlink device on WA + clear local session store
            log.info("👋 WhatsApp logged out")
        except Exception as exc:
            log.warning("⚠️ WhatsApp logout failed", error=str(exc))
        # Ensure the run loop rebuilds → fresh QR (Stop() is what releases idle()).
        await self._end_client(client)

    async def _enable_receipts(self, client: NewAClient) -> None:
        # Make whatsmeow send delivery receipts (✓✓) for incoming messages; without
        # this a linked device leaves the sender stuck on a single gray tick.
        try:
            await client.set_force_activate_delivery_receipts(True)
        except Exception as exc:
            log.warning("⚠️ Could not enable delivery receipts", error=str(exc))

    async def _mark_read(self, event: MessageEv) -> None:
        # Send a read receipt (blue ticks) for a handled message — the assistant
        # read it and is replying, so the sender should see it as read.
        if not self._send_read_receipts:
            return
        client = self._client
        if client is None:
            return
        # Small randomized lag so the blue ticks don't land the instant the message
        # arrives (a mechanical tell). This runs as a background task, so it does
        # not delay dispatching the message to the agent.
        await asyncio.sleep(random.uniform(*_READ_RECEIPT_DELAY_S))
        src = event.Info.MessageSource
        try:
            await client.mark_read(
                event.Info.ID,
                chat=src.Chat,
                sender=src.Sender,
                receipt=ReceiptType.READ,
                timestamp=event.Info.Timestamp or None,
            )
        except Exception as exc:
            log.warning("⚠️ Could not send read receipt", error=str(exc))

    # -- outbound ----------------------------------------------------------

    async def send_text(self, jid_str: str, text: str) -> None:
        """Send a plain text message to a WhatsApp chat JID string.

        A short randomized "typing…" presence is shown first so the reply reads as
        typed by a person rather than fired back instantly by a bot.
        """
        client = self._client
        if client is None:
            log.warning("⚠️ Cannot send — WhatsApp client not connected")
            return
        jid = _parse_jid(jid_str)
        # Log the exact target (server tells LID vs phone-number JID) so send
        # failures are diagnosable without guessing which addressing was used.
        log.info(f"⬆️ WhatsApp send target — {jid_str}", server=jid.Server, user=jid.User)
        await self._type_before_send(client, jid)
        await self._send_with_retry(lambda: client.send_message(jid, text), jid)
        await self._clear_typing(client, jid)

    async def send_audio(self, jid_str: str, ogg_opus: bytes, *, ptt: bool = True) -> None:
        """Send a voice note (P7). ``ogg_opus`` must already be OGG/Opus bytes;
        with ``ptt=True`` WhatsApp renders a native voice-note bubble.

        A short "recording…" presence precedes it, mirroring send_text's "typing…",
        so a voice reply reads as a person recording rather than an instant bot send.
        """
        client = self._client
        if client is None:
            log.warning("⚠️ Cannot send voice — WhatsApp client not connected")
            return
        jid = _parse_jid(jid_str)
        log.info(f"⬆️ WhatsApp voice target — {jid_str}", server=jid.Server, user=jid.User, ptt=ptt)
        await self._record_before_send(client, jid)
        await self._send_with_retry(lambda: self._send_audio_once(client, jid, ogg_opus, ptt), jid)
        await self._clear_typing(client, jid)

    async def _send_audio_once(self, client: NewAClient, jid: Any, ogg_opus: bytes, ptt: bool) -> None:
        # neonize's send_audio sets the mimetype from libmagic, which sniffs bare
        # "audio/ogg". WhatsApp *mobile* silently refuses to render a PTT bubble
        # unless the codec is spelled out as "audio/ogg; codecs=opus" (grounded in
        # whatsmeow discussion #213 — audio/ogg alone doesn't show on mobile). So
        # build the message ourselves, force the mimetype, then send.
        message = await client.build_audio_message(ogg_opus, ptt=ptt)
        message.audioMessage.mimetype = _PTT_MIMETYPE
        # neonize leaves waveform empty → WhatsApp shows a flat bar. Fill the 64-byte
        # amplitude envelope so the player renders real bars (best-effort — an empty
        # result just falls back to flat, which still plays).
        waveform = await compute_waveform(ogg_opus)
        if waveform:
            message.audioMessage.waveform = waveform
        await client.send_message(jid, message)

    async def send_document(
        self, jid_str: str, data: bytes, *, filename: str, mimetype: str
    ) -> None:
        """Send raw bytes as a file/document (P7 fallback when transcode fails —
        the recipient gets a playable attachment rather than nothing)."""
        client = self._client
        if client is None:
            log.warning("⚠️ Cannot send document — WhatsApp client not connected")
            return
        jid = _parse_jid(jid_str)
        log.info(f"⬆️ WhatsApp document target — {jid_str}", filename=filename, mimetype=mimetype)
        await self._send_with_retry(
            lambda: client.send_document(jid, data, filename=filename, mimetype=mimetype),
            jid,
        )

    async def _send_with_retry(self, send: Callable[[], Awaitable[Any]], jid: Any) -> None:
        # whatsmeow resolves the recipient's device list (a "usync" query) on send,
        # and that query can time out transiently. Retry once after a short backoff
        # before giving up, so one flaky query doesn't silently drop the reply.
        # ``send`` is a thunk so text/audio/document share this retry+tolerance path.
        for attempt in (1, 2):
            try:
                await send()
                return
            except DecodeError as exc:
                # neonize can't parse its own send-return proto, but the message is
                # dispatched Go-side before the return is read — treat as
                # delivered-but-unconfirmed rather than a hard failure.
                log.warning(
                    "⚠️ WhatsApp send return unparseable (message likely delivered)",
                    error=str(exc),
                )
                return
            except SendMessageError as exc:
                if attempt == 1 and "usync" in str(exc).lower():
                    log.warning(
                        "⚠️ WhatsApp send hit a usync (device-list) timeout — retrying once",
                        error=str(exc),
                        target=Jid2String(jid),
                    )
                    await asyncio.sleep(1.5)
                    continue
                raise  # final failure — let the transport surface it

    async def _type_before_send(self, client: NewAClient, jid: Any) -> None:
        # Announce "available" once per connection (WhatsApp only relays typing
        # from an online device), then show "composing" for a short randomized
        # window. All best-effort: a presence failure must never block the reply.
        try:
            # Go "online" just for this reply — WhatsApp only relays a typing
            # indicator from an online device. We go back "offline" in
            # _clear_typing so the account isn't permanently online like a bot.
            await client.send_presence(Presence.AVAILABLE)
            await client.send_chat_presence(
                jid,
                ChatPresence.CHAT_PRESENCE_COMPOSING,
                ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT,
            )
        except Exception as exc:  # presence is a nicety, never fatal
            log.warning("⚠️ Could not send typing presence", error=str(exc))
        await asyncio.sleep(random.uniform(*_TYPING_DELAY_S))

    async def _record_before_send(self, client: NewAClient, jid: Any) -> None:
        # Voice-note equivalent of _type_before_send: show "recording audio…" for a
        # short randomized window so a voice reply reads as a person recording.
        try:
            await client.send_presence(Presence.AVAILABLE)
            await client.send_chat_presence(
                jid,
                ChatPresence.CHAT_PRESENCE_COMPOSING,
                ChatPresenceMedia.CHAT_PRESENCE_MEDIA_AUDIO,
            )
        except Exception as exc:  # presence is a nicety, never fatal
            log.warning("⚠️ Could not send recording presence", error=str(exc))
        await asyncio.sleep(random.uniform(*_TYPING_DELAY_S))

    async def _clear_typing(self, client: NewAClient, jid: Any) -> None:
        # Sending the message already clears the indicator on the recipient side;
        # send an explicit "paused", then go "unavailable" so we don't linger
        # online between replies (a permanently-online account is a bot tell).
        try:
            await client.send_chat_presence(
                jid,
                ChatPresence.CHAT_PRESENCE_PAUSED,
                ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT,
            )
            await client.send_presence(Presence.UNAVAILABLE)
        except Exception as exc:
            log.warning("⚠️ Could not clear typing presence", error=str(exc))

    # -- handler registration ---------------------------------------------

    def _register_handlers(self) -> None:
        # neonize calls each handler as ``handler(client, event)``; passing bound
        # methods keeps them as top-level methods (no nested functions).
        #
        # QR is special: it is NOT a normal ``event(...)`` type. neonize's default
        # QR handler prints to the terminal via segno (lost when stdout is
        # redirected), so we register our own via ``client.qr(...)`` to capture the
        # raw bytes and forward them to the Admin UI / log instead.
        self._client.qr(self._on_qr_event)
        self._client.event(PairStatusEv)(self._on_pair_status)
        self._client.event(ConnectedEv)(self._on_connected)
        self._client.event(DisconnectedEv)(self._on_disconnected)
        self._client.event(LoggedOutEv)(self._on_logged_out)
        # Terminal / needs-action states (P8 hardening) — each unlinks or blocks the
        # session, so the account must be re-paired (or the ban waited out).
        self._client.event(TemporaryBanEv)(self._on_temporary_ban)
        self._client.event(ConnectFailureEv)(self._on_connect_failure)
        self._client.event(StreamReplacedEv)(self._on_stream_replaced)
        self._client.event(ClientOutdatedEv)(self._on_client_outdated)
        self._client.event(MessageEv)(self._on_message_event)

    # -- neonize event handlers -------------------------------------------

    async def _on_qr_event(self, client: NewAClient, data_qr: bytes) -> None:
        # neonize's qr callback delivers the raw pairing payload as bytes.
        code = data_qr.decode("utf-8", "replace") if data_qr else ""
        if not code:
            return
        log.info("🔗 WhatsApp QR issued — scan to link the account")
        self._arm_qr_watchdog(client)
        try:
            await self._on_qr(code)
        except Exception as exc:
            log.error("❌ QR callback failed", error=str(exc), exc_info=True)

    async def _on_pair_status(self, _client: NewAClient, event: PairStatusEv) -> None:
        account = getattr(event.ID, "User", "") if event.ID else ""
        self._cancel_qr_watchdog()  # linked: the QR window must not be recycled
        log.info(f"✅ WhatsApp paired — {account}")
        await self._safe_status("paired", {"account": account})

    async def _on_connected(self, _client: NewAClient, _event: ConnectedEv) -> None:
        log.info("✅ WhatsApp connected")
        self._cancel_qr_watchdog()
        self._was_connected = True
        await self._safe_status("connected", {})

    async def _on_disconnected(self, _client: NewAClient, _event: DisconnectedEv) -> None:
        log.warning("⚠️ WhatsApp disconnected")
        await self._safe_status("disconnected", {})

    async def _on_logged_out(self, _client: NewAClient, event: LoggedOutEv) -> None:
        # Session invalidated (device unlinked from the phone). Re-pairing needs a
        # fresh QR — the run loop rebuilds and issues one. Surface the reason so the
        # UI can tell "you unlinked it" from a server-forced logout.
        reason = str(getattr(event, "Reason", "") or "")
        log.warning("⚠️ WhatsApp logged out — re-pair required", reason=reason)
        await self._safe_status("logged_out", {"reason": reason})

    async def _on_temporary_ban(self, _client: NewAClient, event: TemporaryBanEv) -> None:
        # WhatsApp temporarily banned the account (often from automation heuristics).
        # Terminal until the ban expires; surface the code + expiry for the UI.
        code = str(getattr(event, "Code", "") or "")
        expire = str(getattr(event, "Expire", "") or "")
        log.error("❌ WhatsApp temporary ban", code=code, expire=expire)
        await self._safe_status("banned", {"code": code, "expire": expire})

    async def _on_connect_failure(self, _client: NewAClient, event: ConnectFailureEv) -> None:
        # Handshake refused by WhatsApp (bad session, forced logout, etc.). Report as
        # an error with the reason/message; the reconnect loop keeps retrying.
        reason = str(getattr(event, "Reason", "") or "")
        message = str(getattr(event, "Message", "") or "")
        log.error("❌ WhatsApp connect failure", reason=reason, message=message)
        await self._safe_status("error", {"reason": reason, "message": message})

    async def _on_stream_replaced(self, _client: NewAClient, _event: StreamReplacedEv) -> None:
        # Another WhatsApp Web/Desktop client took over this session — we're bumped
        # off and must re-pair to resume.
        log.warning("⚠️ WhatsApp stream replaced — another linked client took over")
        await self._safe_status("replaced", {})

    async def _on_client_outdated(self, _client: NewAClient, _event: ClientOutdatedEv) -> None:
        # WhatsApp rejected the client version — the bundled whatsmeow needs updating.
        log.error("❌ WhatsApp client outdated — neonize/whatsmeow needs an update")
        await self._safe_status("error", {"reason": "client_outdated"})

    async def _on_message_event(self, _client: NewAClient, event: MessageEv) -> None:
        try:
            inbound = _extract_inbound(event)
        except Exception as exc:
            log.error("❌ Failed to parse inbound WhatsApp message", error=str(exc), exc_info=True)
            return
        if inbound.get("is_from_me"):
            return  # ignore our own echoes to avoid loops
        # A @lid reply target makes whatsmeow's send fail ("failed to get device
        # list: usync query timed out" — it can't resolve a LID's devices).
        # Translate to the phone-number JID now, while we still hold the real
        # sender JID object, so the reply is addressable.
        await self._resolve_reply_pn(inbound, event)
        # Voice notes (P6): download the audio bytes so the plugin can hand them to
        # the STT pipeline. Done here where we still hold the raw Message proto.
        if inbound.get("has_audio"):
            await self._attach_audio(event, inbound)
        # Blue ticks after a short human lag — scheduled, not awaited, so the read
        # receipt's delay doesn't hold up dispatching the message to the agent.
        self._schedule(self._mark_read(event))
        try:
            await self._on_message(inbound)
        except Exception as exc:
            log.error("❌ Inbound callback failed", error=str(exc), exc_info=True)

    async def _attach_audio(self, event: MessageEv, inbound: dict[str, Any]) -> None:
        # Download the voice-note bytes (OGG/Opus) and base64 them onto the inbound
        # dict; the server's STT node accepts base64 audio as-is (no transcoding).
        client = self._client
        if client is None:
            return
        try:
            data = await client.download_any(event.Message)
        except Exception as exc:
            log.warning("⚠️ Could not download WhatsApp voice note", error=str(exc))
            return
        if not data:
            return
        am = event.Message.audioMessage
        # Integrity check: WhatsApp declares fileSha256 = SHA-256 of the *decrypted*
        # media. If our downloaded bytes don't match, neonize's download returned
        # corrupt data (vs a downstream base64/persist problem) — this pinpoints it.
        declared = bytes(am.fileSHA256 or b"")
        actual = hashlib.sha256(data).digest()
        log.info(
            "🎧 WhatsApp voice downloaded",
            size=len(data),
            declared_len=int(am.fileLength or 0),
            sha_match=(bool(declared) and actual == declared),
            head=data[:8].hex(),
        )
        # Drop any "; codecs=opus" suffix — STT providers key on the base mime type.
        mime = (am.mimetype or "audio/ogg").split(";")[0].strip()
        inbound["audio_b64"] = base64.b64encode(data).decode("ascii")
        inbound["audio_mime"] = mime
        inbound["audio_seconds"] = int(am.seconds or 0)
        inbound["audio_size"] = len(data)

    async def _resolve_reply_pn(self, inbound: dict[str, Any], event: MessageEv) -> None:
        # Only needed when the reply target is a LID (…@lid); a phone-number JID
        # already sends fine. Look the PN up in whatsmeow's local LID map (a store
        # read, no network — so it can't time out like the send's usync query) and
        # rewrite the reply target to it.
        reply = str(inbound.get("reply_jid") or "")
        if not reply.endswith("@lid"):
            return
        client = self._client
        if client is None:
            return
        src = event.Info.MessageSource
        lid_jid = src.Sender if getattr(src.Sender, "Server", "") == "lid" else src.Chat
        try:
            # Strip the device index (JIDToNonAD) so the lookup is per-user.
            pn = await client.get_pn_from_lid(JIDToNonAD(lid_jid))
        except Exception as exc:  # store miss or neonize return-decode defect
            log.warning(
                "⚠️ Could not resolve LID → phone number; reply may fail to send",
                error=str(exc),
                lid=reply,
            )
            return
        user = getattr(pn, "User", "") if pn else ""
        if not user:
            log.warning("⚠️ LID → phone number returned empty; reply may fail", lid=reply)
            return
        resolved = Jid2String(build_jid(user, "s.whatsapp.net"))
        log.info("🔁 Resolved LID → phone number for reply", lid=reply, pn=resolved)
        inbound["reply_jid"] = resolved

    # -- helpers -----------------------------------------------------------

    async def _safe_status(self, state: str, detail: dict[str, Any]) -> None:
        try:
            await self._on_status(state, detail)
        except Exception as exc:
            log.error("❌ Status callback failed", state=state, error=str(exc), exc_info=True)


def _consume_result(task: asyncio.Future[Any]) -> None:
    # Done-callback for an abandoned neonize idle() (see WhatsAppBridge._idle).
    if not task.cancelled() and task.exception() is not None:
        log.warning("⚠️ Abandoned WhatsApp client ended with an error", error=str(task.exception()))


def _parse_jid(jid_str: str):
    """Rebuild a neonize JID from a ``user@server`` string (kept library-local)."""
    user, _, server = jid_str.partition("@")
    # Strip any device (":86") / agent (".N") suffix — a send must target the bare
    # *user* JID so whatsmeow resolves the recipient's full device list. Addressing
    # a specific device (e.g. "201203…:86") makes the send's usync query time out
    # ("failed to get device list"), because that is not a resolvable user.
    user = user.split(":", 1)[0].split(".", 1)[0]
    return build_jid(user, server or "s.whatsapp.net")


def _extract_inbound(event: MessageEv) -> dict[str, Any]:
    """Flatten a neonize ``MessageEv`` into a plain dict the plugin can use.

    Kept neonize-specific so the plugin/translation layers stay library-agnostic.
    """
    source = event.Info.MessageSource
    message = event.Message

    text = message.conversation
    if not text and message.HasField("extendedTextMessage"):
        text = message.extendedTextMessage.text

    chat_jid = Jid2String(source.Chat)
    # When a contact is addressed by LID (…@lid), SenderAlt carries the
    # phone-number JID. Replying to the PN avoids the "no signal session" /
    # prekey failures whatsmeow hits sending to some LID devices.
    alt = source.SenderAlt
    sender_alt = Jid2String(alt) if getattr(alt, "User", "") else ""
    if source.IsGroup:
        reply_jid = chat_jid
    elif sender_alt.endswith("@s.whatsapp.net"):
        reply_jid = sender_alt
    else:
        reply_jid = chat_jid

    # Phone number (bare user part) for allow-list matching: prefer the PN alt,
    # else the sender itself if it is already a phone-number JID.
    if sender_alt.endswith("@s.whatsapp.net"):
        sender_pn = getattr(alt, "User", "")
    elif Jid2String(source.Sender).endswith("@s.whatsapp.net"):
        sender_pn = getattr(source.Sender, "User", "")
    else:
        sender_pn = ""

    return {
        "msg_id": event.Info.ID,
        "chat_jid": chat_jid,
        "reply_jid": reply_jid,  # preferred outbound target (PN when available)
        "sender_jid": Jid2String(source.Sender),
        "sender_alt": sender_alt,
        "sender_pn": sender_pn,  # bare phone digits for allow-list
        "sender_user": getattr(source.Sender, "User", ""),
        "pushname": event.Info.Pushname,
        "is_from_me": bool(source.IsFromMe),
        "is_group": bool(source.IsGroup),
        "text": text or "",
        "has_audio": message.HasField("audioMessage"),
    }
