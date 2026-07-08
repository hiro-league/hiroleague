"""WhatsAppChannel — the ChannelPlugin the ChannelManager drives.

Phase 1: link the account via QR, persist the session, and log inbound messages.
Routing inbound → agent and sending replies arrive in Phase 2; audio in P6/P7.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from hiro_channel_sdk.base import ChannelPlugin
from hiro_channel_sdk.models import ChannelInfo, ContentItem, MessageRouting, UnifiedMessage
from hiro_commons.log import Logger

from .wa_client import WhatsAppBridge

log = Logger.get("WHATSAPP")

# Fallback session location when the server hasn't pushed one via config.
# Phase 3 (config editor) will push a workspace-scoped path; until then a single
# dev workspace uses this home-dir default.
_DEFAULT_SESSION_DB = Path.home() / ".hiro" / "whatsapp" / "session.db"


class WhatsAppChannel(ChannelPlugin):
    """WhatsApp channel backed by neonize (whatsmeow multi-device)."""

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._bridge: WhatsAppBridge | None = None
        self._task: asyncio.Task[None] | None = None
        self._session_db: str = ""

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            name="whatsapp",
            version="0.1.0",
            description="WhatsApp channel (neonize / whatsmeow multi-device).",
        )

    async def on_configure(self, config: dict[str, Any]) -> None:
        self._config = dict(config or {})
        log.info("WhatsApp channel configured", keys=sorted(self._config.keys()))

    async def on_start(self) -> None:
        self._session_db = str(self._config.get("session_db_path") or _DEFAULT_SESSION_DB)
        log.info("🔌 Starting WhatsApp channel", session_db=self._session_db)
        self._bridge = WhatsAppBridge(
            self._session_db,
            on_qr=self._handle_qr,
            on_status=self._handle_status,
            on_message=self._handle_inbound,
        )
        # Run the client loop in the background so on_start returns and the
        # transport keeps servicing the ChannelManager connection.
        self._task = asyncio.create_task(self._bridge.run())

    async def on_stop(self) -> None:
        log.info("Stopping WhatsApp channel")
        if self._bridge is not None:
            await self._bridge.stop()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send(self, message: UnifiedMessage) -> None:
        # P2: outbound text replies. P7 will add the message.voiced (audio) event.
        if message.message_type != "message":
            return
        if self._bridge is None:
            log.warning("⚠️ WhatsApp send skipped — bridge not started")
            return
        text = _first_text_body(message.content)
        # Reply target: the server's reply envelope leaves recipient_id unset
        # (broadcast), but copies inbound metadata — so the WhatsApp chat JID we
        # stashed on the inbound message round-trips back here.
        jid = message.routing.recipient_id or str(message.routing.metadata.get("wa_chat_jid") or "")
        if not text or not jid:
            log.warning("⚠️ WhatsApp send skipped — no text or target", has_text=bool(text), jid=jid)
            return
        await self._bridge.send_text(jid, text)
        log.info(f"⬆️ WhatsApp sent — {jid} · text", preview=text[:80])

    # -- bridge callbacks --------------------------------------------------

    async def _handle_qr(self, code: str) -> None:
        # No Admin UI yet (that's P4). ASCII-in-a-log is unreliable to scan and the
        # code rotates every ~20s, so also write a clean PNG (overwritten each
        # rotation) the user can open and scan. Emit the raw code for the future UI.
        png_path = self._write_qr_png(code)
        if png_path:
            log.info(f"📱 Scan the WhatsApp QR image to link the account → {png_path}")
        else:
            ascii_qr = _render_ascii_qr(code)
            if ascii_qr:
                log.info(f"📱 Scan this WhatsApp QR to link the account:\n{ascii_qr}")
        await self.emit_event("whatsapp.qr", {"qr": code})

    def _write_qr_png(self, code: str) -> str:
        """Write the current QR to ``<session dir>/qr.png``; empty str on failure."""
        try:
            import qrcode  # optional dep declared in pyproject

            path = Path(self._session_db).parent / "qr.png"
            qrcode.make(code).save(str(path))
            return str(path)
        except Exception as exc:  # image write is a convenience, never fatal
            log.warning("⚠️ Could not write QR png", error=str(exc))
            return ""

    async def _handle_status(self, state: str, detail: dict[str, Any]) -> None:
        log.info(f"WhatsApp status — {state}", **detail)
        await self.emit_event("whatsapp.status", {"state": state, **detail})

    async def _handle_inbound(self, inbound: dict[str, Any]) -> None:
        kind = "voice" if inbound.get("has_audio") else "text"
        preview = inbound.get("text", "")[:80]
        log.info(
            f"⬇️ WhatsApp received — {inbound.get('pushname') or inbound.get('sender_user')} · {kind}",
            preview=preview,
            sender=inbound.get("sender_jid"),
            msg_id=inbound.get("msg_id"),
        )
        text = inbound.get("text") or ""
        if not text:
            # Voice notes / other media are handled from Phase 6 onward.
            log.info("WhatsApp non-text message ignored (text-only until P6)", kind=kind)
            return
        um = UnifiedMessage(
            routing=MessageRouting(
                channel="whatsapp",
                direction="inbound",
                sender_id=inbound.get("sender_jid", ""),
                recipient_id="server",
                # Round-trip the reply target JID so the reply's send() can address
                # it — the server copies inbound metadata onto the outbound reply.
                # reply_jid prefers the phone-number JID over LID (see wa_client).
                metadata={"wa_chat_jid": inbound.get("reply_jid") or inbound.get("chat_jid", "")},
            ),
            content=[ContentItem(content_type="text", body=text)],
        )
        await self.emit(um)


def _first_text_body(content: list[ContentItem]) -> str:
    """Return the first non-empty text item body, or ''."""
    for item in content:
        if item.content_type == "text" and item.body:
            return item.body
    return ""


def _render_ascii_qr(code: str) -> str:
    """Render a pairing string as an ASCII QR block; empty string if unavailable."""
    try:
        import qrcode  # optional dep declared in pyproject

        qr = qrcode.QRCode(border=1)
        qr.add_data(code)
        qr.make(fit=True)
        buf = io.StringIO()
        qr.print_ascii(out=buf, invert=True)
        return buf.getvalue()
    except Exception as exc:  # rendering is a convenience, never fatal
        log.warning("⚠️ Could not render ASCII QR; raw code emitted only", error=str(exc))
        return ""
