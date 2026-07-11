"""WhatsAppChannel — the ChannelPlugin the ChannelManager drives.

Phase 1: link the account via QR, persist the session, and log inbound messages.
Routing inbound → agent and sending replies arrive in Phase 2; audio in P6/P7.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
from pathlib import Path
from typing import Any

from hiro_channel_sdk.base import ChannelPlugin
from hiro_channel_sdk.constants import (
    EVENT_TYPE_MESSAGE_VOICED,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
)
from hiro_channel_sdk.models import (
    ChannelInfo,
    ContentItem,
    EventPayload,
    MessageRouting,
    UnifiedMessage,
)
from hiro_commons.log import Logger

from .audio import TranscodeError, ensure_ffmpeg_on_path, transcode_to_ogg_opus
from .wa_client import WhatsAppBridge

log = Logger.get("WHATSAPP")

# Home-dir fallback used only when the plugin wasn't told its workspace (no
# --log-dir). Normally the session lives in the workspace (see _default_session).
_HOME_SESSION_DB = Path.home() / ".hiro" / "whatsapp" / "session.db"


class WhatsAppChannel(ChannelPlugin):
    """WhatsApp channel backed by neonize (whatsmeow multi-device)."""

    def __init__(self, log_dir: str = "") -> None:
        self._log_dir = log_dir
        self._config: dict[str, Any] = {}
        self._bridge: WhatsAppBridge | None = None
        self._task: asyncio.Task[None] | None = None
        self._ffmpeg_task: asyncio.Task[bool] | None = None
        self._session_db: str = ""
        # Config-driven policy (P3). Defaults: accept everyone, send read receipts.
        self._allowed_senders: set[str] = set()
        self._send_read_receipts: bool = True
        self._owner_number: str = ""  # user's own number → routes to General/Hiro
        # P7: relay TTS replies as WhatsApp voice notes. On by default — if the
        # character speaks (TTS ran), WhatsApp gets the voice note too.
        self._audio_out: bool = True

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            name="whatsapp",
            version="0.1.0",
            description="WhatsApp channel (neonize / whatsmeow multi-device).",
        )

    def _default_session(self) -> Path:
        # The ChannelManager passes --log-dir = <workspace>/logs, so the workspace
        # is its parent — keep the WhatsApp session inside the workspace.
        if self._log_dir:
            return Path(self._log_dir).parent / "channels" / "whatsapp" / "session.db"
        return _HOME_SESSION_DB

    async def on_configure(self, config: dict[str, Any]) -> None:
        self._config = dict(config or {})
        self._send_read_receipts = bool(self._config.get("send_read_receipts", True))
        self._audio_out = bool(self._config.get("audio_out", True))
        self._owner_number = _normalize_number(str(self._config.get("owner_number") or ""))
        # Allow-list is CLOSED by default (security): with nothing configured, no
        # sender may reach the agent. The owner's own number is always permitted;
        # add more via `allowed_senders`.
        raw_allowed = self._config.get("allowed_senders") or []
        allowed = {_normalize_number(str(s)) for s in raw_allowed if str(s).strip()}
        if self._owner_number:
            allowed.add(self._owner_number)
        self._allowed_senders = allowed
        if not self._allowed_senders:
            log.warning(
                "⚠️ WhatsApp allow-list is empty — NO senders permitted. Set "
                "'owner_number' or 'allowed_senders' for the agent to receive messages."
            )
        log.info(
            "WhatsApp channel configured",
            keys=sorted(self._config.keys()),
            allowed=len(self._allowed_senders),
            read_receipts=self._send_read_receipts,
            audio_out=self._audio_out,
            owner_set=bool(self._owner_number),
        )

    async def on_start(self) -> None:
        self._session_db = str(self._config.get("session_db_path") or self._default_session())
        log.info("🔌 Starting WhatsApp channel", session_db=self._session_db)
        # Provision ffmpeg/ffprobe (needed for outbound voice) in the background so
        # a first-run binary download never delays startup or QR pairing. The first
        # voice reply can only happen after the user messages in, so there's ample
        # time; if it fails, voice falls back to sending audio as a file.
        if self._audio_out:
            self._ffmpeg_task = asyncio.create_task(ensure_ffmpeg_on_path())
        self._bridge = WhatsAppBridge(
            self._session_db,
            on_qr=self._handle_qr,
            on_status=self._handle_status,
            on_message=self._handle_inbound,
            send_read_receipts=self._send_read_receipts,
        )
        # Run the client loop in the background so on_start returns and the
        # transport keeps servicing the ChannelManager connection.
        self._task = asyncio.create_task(self._bridge.run())

    async def on_stop(self) -> None:
        log.info("Stopping WhatsApp channel")
        if self._bridge is not None:
            await self._bridge.stop()
        if self._ffmpeg_task is not None and not self._ffmpeg_task.done():
            self._ffmpeg_task.cancel()  # abandon an in-flight ffmpeg download on shutdown
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def on_event(self, event: str, data: dict[str, Any]) -> None:
        # Admin-driven actions (P5): log out / re-pair or force reconnect.
        if self._bridge is None:
            return
        if event == "whatsapp.logout":
            await self._bridge.logout()
        elif event == "whatsapp.reconnect":
            await self._bridge.reconnect()

    async def send(self, message: UnifiedMessage) -> None:
        # Outbound dispatch. A reply arrives as a "message" (text) and, when the
        # character has TTS, additionally as an "event" (message.voiced) carrying
        # the spoken audio — P2 handles the former, P7 the latter.
        if self._bridge is None:
            log.warning("⚠️ WhatsApp send skipped — bridge not started")
            return
        # Reply target: the server's reply envelope leaves recipient_id unset
        # (broadcast) but copies inbound metadata — so the WhatsApp chat JID we
        # stashed on the inbound message round-trips back here.
        jid = _reply_jid(message)
        if not jid:
            log.warning("⚠️ WhatsApp send skipped — no reply target", kind=message.message_type)
            return
        if message.message_type == MESSAGE_TYPE_EVENT:
            await self._send_event(message, jid)
        elif message.message_type == MESSAGE_TYPE_MESSAGE:
            await self._send_text_message(message, jid)

    async def _send_text_message(self, message: UnifiedMessage, jid: str) -> None:
        text = _first_text_body(message.content)
        if not text:
            log.warning("⚠️ WhatsApp send skipped — no text body", jid=jid)
            return
        await self._bridge.send_text(jid, text)
        log.info(f"⬆️ WhatsApp sent — {jid} · text", preview=text[:80])

    async def _send_event(self, message: UnifiedMessage, jid: str) -> None:
        # Only message.voiced is actionable on WhatsApp today (other events —
        # transcribed, received — are device-facing modality mirrors, no-ops here).
        event = message.event
        if event is None or event.type != EVENT_TYPE_MESSAGE_VOICED:
            return
        if not self._audio_out:
            log.info("WhatsApp voice reply suppressed — audio_out disabled", jid=jid)
            return
        await self._send_voice_note(event, jid)

    async def _send_voice_note(self, event: EventPayload, jid: str) -> None:
        audio_b64 = str(event.data.get("audio") or "")
        if not audio_b64:
            log.warning("⚠️ WhatsApp voiced event carried no audio", jid=jid)
            return
        try:
            mp3 = base64.b64decode(audio_b64)
        except (ValueError, binascii.Error) as exc:
            log.warning("⚠️ WhatsApp voiced audio was not valid base64", error=str(exc))
            return
        # A native voice-note bubble requires OGG/Opus + PTT (design §9); the TTS
        # pipeline yields MP3, so transcode. On failure, fall back to a file so the
        # user still hears the reply (just not as a voice bubble).
        try:
            ogg = await transcode_to_ogg_opus(mp3)
        except TranscodeError as exc:
            log.warning(
                "⚠️ WhatsApp voice transcode failed — sending audio as file",
                error=str(exc),
                jid=jid,
            )
            await self._send_voice_fallback(mp3, event, jid)
            return
        await self._bridge.send_audio(jid, ogg, ptt=True)
        log.info(f"⬆️ WhatsApp sent — {jid} · voice", size=len(ogg))

    async def _send_voice_fallback(self, mp3: bytes, event: EventPayload, jid: str) -> None:
        mime = str(event.data.get("mime_type") or "audio/mpeg")
        ext = "mp3" if "mpeg" in mime else "ogg"
        try:
            await self._bridge.send_document(jid, mp3, filename=f"reply.{ext}", mimetype=mime)
            log.info(f"⬆️ WhatsApp sent — {jid} · voice (file fallback)", size=len(mp3))
        except Exception as exc:  # external send boundary — surface, don't crash send()
            log.error("❌ WhatsApp voice fallback failed", error=str(exc), exc_info=True, jid=jid)

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
        # Allow-list is closed by default: only explicitly permitted numbers reach
        # the agent (unknown/LID-only senders with no phone match are dropped).
        pn = _normalize_number(inbound.get("sender_pn", ""))
        if pn not in self._allowed_senders:
            log.info(
                "WhatsApp inbound ignored — sender not permitted (allow-list closed)",
                sender=inbound.get("sender_jid"),
                allowed=len(self._allowed_senders),
            )
            return
        kind = "voice" if inbound.get("has_audio") else "text"
        preview = inbound.get("text", "")[:80]
        log.info(
            f"⬇️ WhatsApp received — {inbound.get('pushname') or inbound.get('sender_user')} · {kind}",
            preview=preview,
            sender=inbound.get("sender_jid"),
            msg_id=inbound.get("msg_id"),
        )
        text = inbound.get("text") or ""
        # Build the content item: a voice note (P6) → audio, otherwise text. The
        # server's STT node transcribes audio; anything else with no text is dropped.
        if inbound.get("audio_b64"):
            content = ContentItem(
                content_type="audio",
                body=inbound["audio_b64"],
                metadata={
                    "mime_type": inbound.get("audio_mime", "audio/ogg"),
                    "duration_ms": int(inbound.get("audio_seconds", 0)) * 1000,
                    "size": inbound.get("audio_size", 0),
                },
            )
        elif text:
            content = ContentItem(content_type="text", body=text)
        else:
            log.info("WhatsApp message ignored — no text or audio", kind=kind)
            return
        metadata: dict[str, Any] = {
            # Round-trip the reply target JID so the reply's send() can address it —
            # the server copies inbound metadata onto the outbound reply. reply_jid
            # prefers the phone-number JID over LID (see wa_client).
            "wa_chat_jid": inbound.get("reply_jid") or inbound.get("chat_jid", ""),
        }
        # Reply in kind (P7): a voice note in → ask the graph for a spoken reply.
        # request_voice_reply drives the graph's TTS gate (agent_manager reads it
        # from inbound metadata); the resulting message.voiced event is what send()
        # relays as a native WhatsApp voice note. Gated by audio_out; a text
        # message gets a text reply as before. Set only for audio so we don't voice
        # every text turn.
        if self._audio_out and inbound.get("audio_b64"):
            metadata["request_voice_reply"] = True
        # Owner's own number → route to the General/Hiro thread, not a per-sender one.
        if self._owner_number and _normalize_number(inbound.get("sender_pn", "")) == self._owner_number:
            metadata["route_to_default"] = True
        um = UnifiedMessage(
            routing=MessageRouting(
                channel="whatsapp",
                direction="inbound",
                sender_id=inbound.get("sender_jid", ""),
                recipient_id="server",
                metadata=metadata,
            ),
            content=[content],
        )
        await self.emit(um)


def _reply_jid(message: UnifiedMessage) -> str:
    """Resolve the WhatsApp chat JID to reply to from an outbound envelope."""
    return message.routing.recipient_id or str(message.routing.metadata.get("wa_chat_jid") or "")


def _normalize_number(raw: str) -> str:
    """Reduce a phone number / JID user part to bare digits for allow-list matching."""
    return "".join(ch for ch in raw if ch.isdigit())


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
