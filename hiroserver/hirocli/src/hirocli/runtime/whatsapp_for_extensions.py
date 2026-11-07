"""WhatsApp for extensions — the plan's Phase 4: HomeHiro's messages go out through the core.

Three requests, open to extensions only (the app doesn't get them by being paired):

  whatsapp.send    send text, a picture (text = caption) or a ready OGG voice note to a
                   number; answered once WhatsApp took it, or with why not
  whatsapp.check   which numbers have WhatsApp (HomeHiro checks a contact when it's saved)
  whatsapp.status  WhatsApp's state as the plugin last reported it (HomeHiro's System health)

Contract (params, answers, error codes) in ``hiro_channel_sdk.constants``. The core asks
the WhatsApp plugin with ``channel.call`` and waits for its answer: a reply (channel.send)
is handed over and forgotten, which can't say "sent" or why not.

A message to the owner's number is also written to the owner's conversation and to Hiro's
own thread, so the owner sees it in the app and Hiro knows it was said when the owner
replies. Messages to anyone else are only sent (other people don't talk to Hiro yet).

Not exposed as a Tool (CLI / agent / HTTP) on purpose: no new features in Phase 4. A Tool
can wrap the same plugin call later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hiro_channel_sdk.constants import (
    METHOD_WHATSAPP_CHECK,
    METHOD_WHATSAPP_SEND,
    METHOD_WHATSAPP_STATUS,
    WHATSAPP_CALL_CHECK,
    WHATSAPP_CALL_SEND,
    WHATSAPP_CHECK_MAX,
    WHATSAPP_ERROR_FAILED,
    WHATSAPP_ERROR_NOT_CONNECTED,
    WHATSAPP_ERROR_NOT_RUNNING,
)
from hiro_commons.log import Logger

from .channel_manager import ChannelCallError
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("WHATSAPP_EXT")

WHATSAPP_CHANNEL = "whatsapp"

# The extension waits up to 60 s for a send; the plugin gets most of that.
SEND_TIMEOUT_S = 50.0
_CHECK_TIMEOUT_S = 25.0

# What's passed to the plugin. ``transcript`` stays in the core: it's only written
# to the owner's conversation, never sent.
_SEND_KEYS = ("to", "text", "image_b64", "voice_b64", "voice_seconds", "waveform_b64")


def sender_label(ctx: RequestContext) -> str:
    """The extension's name for logs (who signed in), else its id."""
    sender = getattr(getattr(ctx.msg, "routing", None), "sender_id", "") or "extension"
    ext = ctx.server_ctx.extension_manager
    if ext is not None:
        live = ext.snapshot().get(sender)
        if live:
            return str(live.get("name") or sender)
    return sender


def digits(value: str) -> str:
    """The number part of a number or JID, as bare digits ("2010…@s.whatsapp.net" → "2010…")."""
    return "".join(ch for ch in value.partition("@")[0].split(":", 1)[0] if ch.isdigit())


def _refusal(exc: ChannelCallError) -> RequestRefused:
    """A plugin answer → the code the extension sees."""
    if exc.reason == "not_running":
        return RequestRefused(WHATSAPP_ERROR_NOT_RUNNING, "WhatsApp isn't running in HiroLeague")
    if exc.reason in (WHATSAPP_ERROR_NOT_CONNECTED, WHATSAPP_ERROR_FAILED, "invalid_params"):
        return RequestRefused(exc.reason, str(exc))
    return RequestRefused(WHATSAPP_ERROR_FAILED, str(exc))


def _validated_send(params: dict[str, Any]) -> dict[str, Any]:
    to = str(params.get("to") or "").strip()
    if not digits(to):
        raise RequestRefused("invalid_params", "Who to send to is missing (a number with its country code)")
    text = str(params.get("text") or "")
    has_image = bool(params.get("image_b64"))
    has_voice = bool(params.get("voice_b64"))
    if has_image and has_voice:
        raise RequestRefused("invalid_params", "Send a picture or a voice note, not both")
    if not (text or has_image or has_voice):
        raise RequestRefused("invalid_params", "Nothing to send")
    return {key: params[key] for key in _SEND_KEYS if params.get(key) not in (None, "")}


def owner_number(server_ctx: ServerContext) -> str:
    from ..domain.channel_config import load_channel_config

    cfg = load_channel_config(server_ctx.workspace_path, WHATSAPP_CHANNEL)
    return digits(str((cfg.config if cfg else {}).get("owner_number") or ""))


def _record_text(params: dict[str, Any]) -> str:
    """What the owner's conversation and Hiro's thread show for this message."""
    text = str(params.get("text") or "").strip()
    if params.get("image_b64"):
        return f"{text} (with a picture)" if text else "(a picture)"
    if params.get("voice_b64"):
        transcript = str(params.get("transcript") or "").strip()
        return f"(voice note) {transcript}" if transcript else "(a voice note)"
    return text


async def record_for_owner(server_ctx: ServerContext, params: dict[str, Any], sender: str) -> None:
    """Write a message sent to the owner into the owner's conversation and Hiro's thread.

    Best effort: the message already went out, so a failure here is logged, never
    reported as a failed send.
    """
    from ..domain.conversation_channel import resolve_default_channel, update_last_message_at
    from ..domain.message_store import save_message

    body = _record_text(params)
    if not body:
        return
    try:
        # The owner's WhatsApp lands in the default (General) conversation (the
        # plugin's route_to_default), so that's where this goes too.
        conv = resolve_default_channel(server_ctx.workspace_path)
        await save_message(
            server_ctx.workspace_path,
            external_id=f"ext-{uuid4().hex}",
            channel_id=int(conv.id),
            sender_type="agent",
            sender_id="server",
            content_type="text",
            body=body,
            metadata={"sent_for": {"extension": sender, "channel": WHATSAPP_CHANNEL}},
        )
        update_last_message_at(server_ctx.workspace_path, int(conv.id))
    except Exception as exc:
        log.error("❌ Couldn't write the owner's message to the conversation", error=str(exc), exc_info=True)
        return
    agent = server_ctx.agent_manager
    if agent is None:
        return
    try:
        await agent.add_sent_message(int(conv.id), body)
    except Exception as exc:
        log.error("❌ Couldn't add the owner's message to Hiro's thread", error=str(exc), exc_info=True)


async def handle_whatsapp_send(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    send = _validated_send(params)
    server_ctx = ctx.server_ctx
    sender = sender_label(ctx)
    channels = server_ctx.channel_manager
    if channels is None:
        raise RequestRefused(WHATSAPP_ERROR_NOT_RUNNING, "WhatsApp isn't running in HiroLeague")
    to = send["to"]
    try:
        await channels.call_channel(WHATSAPP_CHANNEL, WHATSAPP_CALL_SEND, send, timeout=SEND_TIMEOUT_S)
    except ChannelCallError as exc:
        raise _refusal(exc) from exc
    is_owner = bool(digits(to)) and digits(to) == owner_number(server_ctx)
    log.info(
        f"⬆️ WhatsApp sent for {sender} — {'the owner' if is_owner else to}",
        kind="picture" if "image_b64" in send else "voice" if "voice_b64" in send else "text",
    )
    if is_owner:
        await record_for_owner(server_ctx, params, sender)
    return {"sent": True}


async def handle_whatsapp_check(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    raw = params.get("numbers")
    if not isinstance(raw, list):
        raise RequestRefused("invalid_params", "numbers must be a list")
    numbers = [str(n).strip() for n in raw if str(n).strip()]
    if not numbers:
        raise RequestRefused("invalid_params", "No numbers to check")
    if len(numbers) > WHATSAPP_CHECK_MAX:
        raise RequestRefused("invalid_params", f"At most {WHATSAPP_CHECK_MAX} numbers at a time")
    channels = ctx.server_ctx.channel_manager
    if channels is None:
        raise RequestRefused(WHATSAPP_ERROR_NOT_RUNNING, "WhatsApp isn't running in HiroLeague")
    try:
        result = await channels.call_channel(
            WHATSAPP_CHANNEL, WHATSAPP_CALL_CHECK, {"numbers": numbers}, timeout=_CHECK_TIMEOUT_S
        )
    except ChannelCallError as exc:
        raise _refusal(exc) from exc
    answers = result.get("answers") if isinstance(result, dict) else None
    return {"answers": answers if isinstance(answers, list) else []}


async def handle_whatsapp_status(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """WhatsApp as the core knows it: whether the plugin runs, and its last report."""
    del params
    server_ctx = ctx.server_ctx
    channels = server_ctx.channel_manager
    running = channels is not None and WHATSAPP_CHANNEL in channels.get_connected_channels()
    live = dict(server_ctx.channel_status.get(WHATSAPP_CHANNEL) or {})
    return {
        "running": running,
        "state": str(live.get("state") or "") if running else "",
        "detail": dict(live.get("detail") or {}) if running else {},
        # A QR is showing in the admin's Channels → WhatsApp: waiting to be linked.
        "waiting_for_link": running and bool(live.get("qr")),
        "account": str(live.get("account") or ""),
    }


# (method, handler, who may call it) — merged into request_methods' table.
WHATSAPP_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_WHATSAPP_SEND, handle_whatsapp_send, EXTENSIONS_ONLY),
    (METHOD_WHATSAPP_CHECK, handle_whatsapp_check, EXTENSIONS_ONLY),
    (METHOD_WHATSAPP_STATUS, handle_whatsapp_status, EXTENSIONS_ONLY),
)
