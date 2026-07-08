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
from pathlib import Path
from typing import Any, Awaitable, Callable

from google.protobuf.message import DecodeError

from hiro_commons.log import Logger

# neonize async client + event types. These load the bundled Go shared library
# (whatsmeow) at import time; that is expected and only happens in this module.
from neonize.aioze.client import NewAClient
from neonize.aioze.events import (
    ConnectedEv,
    DisconnectedEv,
    LoggedOutEv,
    MessageEv,
    PairStatusEv,
)
from neonize.utils import Jid2String, build_jid

log = Logger.get("WHATSAPP.CLIENT")

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
    ) -> None:
        self._session_db_path = session_db_path
        self._on_qr = on_qr
        self._on_status = on_status
        self._on_message = on_message
        self._stopping = False
        self._client: NewAClient | None = None
        # The session DB is created by neonize; ensure its parent dir exists so a
        # fresh install (no prior session) can write it and trigger QR pairing.
        Path(session_db_path).parent.mkdir(parents=True, exist_ok=True)

    # -- lifecycle ---------------------------------------------------------

    def _build_client(self) -> NewAClient:
        client = NewAClient(self._session_db_path)
        self._client = client
        self._register_handlers()
        return client

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
                await client.idle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # external library boundary — never crash silently
                log.error("❌ WhatsApp client loop failed", error=str(exc), exc_info=True)
            if self._stopping:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def stop(self) -> None:
        self._stopping = True
        client = self._client
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception as exc:  # best-effort teardown; log and move on
            log.warning("⚠️ WhatsApp disconnect error", error=str(exc))

    # -- outbound ----------------------------------------------------------

    async def send_text(self, jid_str: str, text: str) -> None:
        """Send a plain text message to a WhatsApp chat JID string."""
        client = self._client
        if client is None:
            log.warning("⚠️ Cannot send — WhatsApp client not connected")
            return
        try:
            await client.send_message(_parse_jid(jid_str), text)
        except DecodeError as exc:
            # neonize can fail to parse its own send-return proto on some sends.
            # The message is dispatched Go-side before the return is read, so treat
            # this as delivered-but-unconfirmed rather than a hard RPC failure.
            log.warning(
                "⚠️ WhatsApp send return unparseable (message likely delivered)",
                error=str(exc),
            )

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
        self._client.event(MessageEv)(self._on_message_event)

    # -- neonize event handlers -------------------------------------------

    async def _on_qr_event(self, _client: NewAClient, data_qr: bytes) -> None:
        # neonize's qr callback delivers the raw pairing payload as bytes.
        code = data_qr.decode("utf-8", "replace") if data_qr else ""
        if not code:
            return
        log.info("🔗 WhatsApp QR issued — scan to link the account")
        try:
            await self._on_qr(code)
        except Exception as exc:
            log.error("❌ QR callback failed", error=str(exc), exc_info=True)

    async def _on_pair_status(self, _client: NewAClient, event: PairStatusEv) -> None:
        account = getattr(event.ID, "User", "") if event.ID else ""
        log.info(f"✅ WhatsApp paired — {account}")
        await self._safe_status("paired", {"account": account})

    async def _on_connected(self, _client: NewAClient, _event: ConnectedEv) -> None:
        log.info("✅ WhatsApp connected")
        await self._safe_status("connected", {})

    async def _on_disconnected(self, _client: NewAClient, _event: DisconnectedEv) -> None:
        log.warning("⚠️ WhatsApp disconnected")
        await self._safe_status("disconnected", {})

    async def _on_logged_out(self, _client: NewAClient, _event: LoggedOutEv) -> None:
        # Session invalidated (unlinked/banned). Re-pairing needs a fresh QR.
        log.warning("⚠️ WhatsApp logged out — re-pair required")
        await self._safe_status("logged_out", {})

    async def _on_message_event(self, _client: NewAClient, event: MessageEv) -> None:
        try:
            inbound = _extract_inbound(event)
        except Exception as exc:
            log.error("❌ Failed to parse inbound WhatsApp message", error=str(exc), exc_info=True)
            return
        if inbound.get("is_from_me"):
            return  # ignore our own echoes to avoid loops
        try:
            await self._on_message(inbound)
        except Exception as exc:
            log.error("❌ Inbound callback failed", error=str(exc), exc_info=True)

    # -- helpers -----------------------------------------------------------

    async def _safe_status(self, state: str, detail: dict[str, Any]) -> None:
        try:
            await self._on_status(state, detail)
        except Exception as exc:
            log.error("❌ Status callback failed", state=state, error=str(exc), exc_info=True)


def _parse_jid(jid_str: str):
    """Rebuild a neonize JID from a ``user@server`` string (kept library-local)."""
    user, _, server = jid_str.partition("@")
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

    return {
        "msg_id": event.Info.ID,
        "chat_jid": chat_jid,
        "reply_jid": reply_jid,  # preferred outbound target (PN when available)
        "sender_jid": Jid2String(source.Sender),
        "sender_alt": sender_alt,
        "sender_user": getattr(source.Sender, "User", ""),  # bare phone number
        "pushname": event.Info.Pushname,
        "is_from_me": bool(source.IsFromMe),
        "is_group": bool(source.IsGroup),
        "text": text or "",
        "has_audio": message.HasField("audioMessage"),
    }
