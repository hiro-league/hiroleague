"""Notify — Hiro tells people something (the plan's Phase 5).

An extension asks the core (``notify``; HomeHiro's "Tell through Hiro" automation step:
"Joe just got home"). Hiro sends it on the medium asked (WhatsApp for now), either as
given (style "exact") or written by its character in its own words ("character"). A
message to the owner is also written to the owner's conversation and to Hiro's thread
(as in Phase 4), so a reply ("where is he now?") follows on. Each person is sent to on
their own: one failing doesn't stop the others.

One operation, two callers: the ``notify`` extension request (below) and ``NotifyTool``
(tools/notify.py). Later, the core's own rules and schedules call the same function.

Text or voice note: always text for now. Hiro's replies answer in kind (a voice note
gets a voice note), which a notification has nothing to answer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import (
    METHOD_NOTIFY,
    NOTIFY_MAX_RECIPIENTS,
    NOTIFY_MEDIUM_WHATSAPP,
    NOTIFY_STYLE_CHARACTER,
    NOTIFY_STYLE_EXACT,
    WHATSAPP_CALL_SEND,
)
from hiro_commons.log import Logger

from .channel_manager import ChannelCallError
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused
from .whatsapp_for_extensions import (
    SEND_TIMEOUT_S,
    WHATSAPP_CHANNEL,
    digits,
    owner_number,
    record_for_owner,
    sender_label,
)

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("NOTIFY")

STYLES = (NOTIFY_STYLE_EXACT, NOTIFY_STYLE_CHARACTER)
MEDIUMS = (NOTIFY_MEDIUM_WHATSAPP,)

# What the character is asked to write (style "character"). The facts are the
# extension's; the words are the character's.
_WRITE_INSTRUCTION = (
    "Write a short WhatsApp message to {name} that tells them the following, in your own "
    "voice and words. Keep every fact and add none. Reply with the message only.\n\n"
    "What to tell: {text}"
)


@dataclass
class Recipient:
    name: str
    number: str  # digits with the country code


@dataclass
class NotifyResult:
    name: str
    number: str
    sent: bool
    error: str | None = None


class NotifyInvalid(ValueError):
    """The request can't be carried out as asked (nothing sent)."""


def parse_recipients(raw: Any) -> list[Recipient]:
    """``[{name, number}, ...]`` → recipients; raises NotifyInvalid."""
    if not isinstance(raw, list) or not raw:
        raise NotifyInvalid("Who to tell is missing: a list of {name, number}")
    if len(raw) > NOTIFY_MAX_RECIPIENTS:
        raise NotifyInvalid(f"At most {NOTIFY_MAX_RECIPIENTS} people at a time")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise NotifyInvalid("Each person is {name, number}")
        number = digits(str(item.get("number") or ""))
        if not number:
            raise NotifyInvalid(f"{item.get('name') or 'Someone'} has no number (digits with the country code)")
        out.append(Recipient(name=str(item.get("name") or "").strip() or number, number=number))
    return out


def check_request(medium: str, text: str, style: str) -> None:
    """Raises NotifyInvalid for an unknown medium or style, or nothing to tell."""
    if medium not in MEDIUMS:
        raise NotifyInvalid(f"Unknown medium {medium!r} (one of: {', '.join(MEDIUMS)})")
    if style not in STYLES:
        raise NotifyInvalid(f"Unknown style {style!r} (one of: {', '.join(STYLES)})")
    if not text.strip():
        raise NotifyInvalid("Nothing to tell: the text is empty")


async def _body(server_ctx: ServerContext, who: Recipient, text: str, style: str, is_owner: bool) -> str:
    """The words that go out: as given, or the character's."""
    if style == NOTIFY_STYLE_EXACT:
        return text
    agent = server_ctx.agent_manager
    if agent is None:
        raise RuntimeError("Hiro isn't running, so its character can't write the message")
    channel_id = None
    if is_owner:
        # The owner talks to Hiro in the default (General) conversation: that conversation's character writes.
        from ..domain.conversation_channel import resolve_default_channel

        channel_id = int(resolve_default_channel(server_ctx.workspace_path).id)
    written, _character = await agent.write_as_character(
        channel_id, _WRITE_INSTRUCTION.format(name=who.name, text=text)
    )
    return written


async def notify(
    server_ctx: ServerContext,
    recipients: list[Recipient],
    *,
    medium: str,
    text: str,
    style: str,
    asked_by: str,
) -> list[NotifyResult]:
    """Tell each person; one result per person, in the order given. Raises NotifyInvalid."""
    check_request(medium, text, style)
    owner = owner_number(server_ctx)
    results: list[NotifyResult] = []
    for who in recipients:
        is_owner = bool(owner) and who.number == owner
        label = "the owner" if is_owner else who.name
        try:
            body = await _body(server_ctx, who, text.strip(), style, is_owner)
            channels = server_ctx.channel_manager
            if channels is None:
                raise ChannelCallError("WhatsApp isn't running in HiroLeague", "not_running")
            await channels.call_channel(
                WHATSAPP_CHANNEL, WHATSAPP_CALL_SEND, {"to": who.number, "text": body}, timeout=SEND_TIMEOUT_S
            )
        except ChannelCallError as exc:
            reason = "WhatsApp isn't running in HiroLeague" if exc.reason == "not_running" else str(exc)
            log.warning(f"⚠️ Notify not sent — {label} · for {asked_by}", error=reason, style=style)
            results.append(NotifyResult(who.name, who.number, False, reason))
            continue
        except Exception as exc:  # the character couldn't write it (no model, the LLM failed)
            log.error(f"❌ Notify not sent — {label} · for {asked_by}", error=str(exc), style=style, exc_info=True)
            results.append(NotifyResult(who.name, who.number, False, f"Hiro couldn't write it: {exc}"))
            continue
        log.info(f"⬆️ Notify sent — {label} · for {asked_by}", style=style, medium=medium, chars=len(body))
        if is_owner:
            await record_for_owner(server_ctx, {"text": body}, asked_by)
        results.append(NotifyResult(who.name, who.number, True))
    return results


async def handle_notify(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """The ``notify`` extension request (contract in hiro_channel_sdk.constants)."""
    try:
        recipients = parse_recipients(params.get("to"))
        results = await notify(
            ctx.server_ctx,
            recipients,
            medium=str(params.get("medium") or NOTIFY_MEDIUM_WHATSAPP),
            text=str(params.get("text") or ""),
            style=str(params.get("style") or NOTIFY_STYLE_EXACT),
            asked_by=sender_label(ctx),
        )
    except NotifyInvalid as exc:
        raise RequestRefused("invalid_params", str(exc)) from exc
    return {"results": [asdict(r) for r in results]}


# (method, handler, who may call it) — merged into request_methods' table.
NOTIFY_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_NOTIFY, handle_notify, EXTENSIONS_ONLY),
)
