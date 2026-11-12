"""WhatsApp: the app's messages go out through the HiroLeague core's WhatsApp, from the home's number.

The core runs WhatsApp (its WhatsApp channel, linked to the home's number in HiroLeague's admin, Channels →
WhatsApp). The app asks it over its extension connection (`hiroleague.link`): `whatsapp.send` (text, a picture with
its caption, or a voice note), `whatsapp.check` (which numbers have WhatsApp) and `whatsapp.status`. People's numbers
are in HiroLeague's family list (family.py `reachable`). Everything the app sends goes through `send()`, which
honours OUTPUTS=off (`Extension.outputs`).

`notify()` asks Hiro to tell someone (the core's `notify`): Hiro sends it on WhatsApp, as given or written by its
character, and names the person by their id in the family list.

Backend kit, step 4: HomeHiro's and NetHiro's copies; HomeHiro's had all of it, NetHiro's the status and text sends.
"""

import base64
from typing import Any, Literal

from hiro_channel_sdk import ExtensionRequestError
from hiro_channel_sdk.constants import (
    METHOD_NOTIFY,
    METHOD_WHATSAPP_CHECK,
    METHOD_WHATSAPP_SEND,
    METHOD_WHATSAPP_STATUS,
    WHATSAPP_CHECK_MAX,
    WHATSAPP_ERROR_FAILED,
    WHATSAPP_ERROR_NOT_CONNECTED,
    WHATSAPP_ERROR_NOT_RUNNING,
    NOTIFY_MEDIUM_WHATSAPP,
    NOTIFY_STYLE_CHARACTER,
    NOTIFY_STYLE_EXACT,
)
from pydantic import BaseModel, ConfigDict

from . import identity
from . import calls
from .errors import Invalid, OutsideError, translate
from .extension import ext
from .hiroleague import link

log = identity.logger("whatsapp")

SEND_TIMEOUT, CHECK_TIMEOUT, STATUS_TIMEOUT = 60.0, 30.0, 10.0  # seconds; a send waits for WhatsApp itself
WHERE = "HiroLeague's admin, Channels → WhatsApp"  # where the number is linked now (no longer in the app)


def _no_core() -> str:
    return f"{identity.app().title} isn't connected to HiroLeague (Settings → HiroLeague)"


class WhatsAppError(OutsideError):
    """HiroLeague's WhatsApp refused or failed a request, or HiroLeague didn't answer (502)."""


class WhatsAppNotRunning(WhatsAppError):
    """Nothing was sent: the app isn't connected to HiroLeague, or HiroLeague's WhatsApp isn't running or linked."""


# What Settings → WhatsApp, the Overview and System health show: the core's states, plus the app's own:
# no_core (HiroLeague can't be asked), not_running (its WhatsApp channel isn't running), starting (it runs
# but has said nothing yet), linking (a QR code is waiting in HiroLeague's admin), connecting (just linked),
# unknown (a state the app doesn't know yet).
WhatsAppState = Literal["no_core", "not_running", "starting", "linking", "connecting", "connected", "reconnecting",
                        "disconnected", "logged_out", "banned", "error", "replaced", "unknown"]


class WhatsAppStatus(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # every answer has every field
    state: WhatsAppState
    account: str | None = None  # the linked number, digits with country code (no "+"), when HiroLeague says it
    note: str | None = None  # what the state means, in words: shown as is
    outputs: bool  # False = OUTPUTS=off: messages are logged, not sent


def describe(running: bool, state: str, detail: dict[str, Any], waiting_for_link: bool) -> tuple[WhatsAppState, str | None]:
    """The core's whatsapp.status answer as the app's state and its words (pure)."""
    if not running:
        return "not_running", f"HiroLeague's WhatsApp isn't running: start it in {WHERE}"
    if waiting_for_link:
        return "linking", f"Waiting to be linked: scan the QR code in {WHERE}"
    reason = str(detail.get("reason") or detail.get("message") or "").strip()
    match state:
        case "connected":
            return "connected", None
        case "":
            return "starting", "HiroLeague's WhatsApp is starting"
        case "paired":
            return "connecting", "Linked; connecting to WhatsApp"
        case "reconnecting":
            return "reconnecting", "Reconnecting to WhatsApp"
        case "disconnected":
            return "disconnected", "Disconnected from WhatsApp"
        case "logged_out":
            why = f" (logged out: {reason})" if reason else " (logged out)"
            return "logged_out", f"Not linked to a number{why}: link it in {WHERE}"
        case "banned":
            code = str(detail.get("code") or "").strip()
            return "banned", "WhatsApp has blocked the number" + (f" (code {code})" if code else "")
        case "error":
            return "error", "WhatsApp failed" + (f": {reason}" if reason else "")
        case "replaced":
            return "replaced", "Another program took over the WhatsApp link"
    return "unknown", f"HiroLeague's WhatsApp says {state!r}"


async def _ask(method: str, params: dict[str, Any], timeout: float, *, sends: bool = False) -> dict[str, Any]:
    """One request to the core, timed; every failure as a WhatsAppError in words.

    sends: the request sends a message, so a failure after it left may still have sent it: say so."""
    client = link.client
    if not client.connected:  # checked first: then a dropped connection below means the request had left
        raise WhatsAppNotRunning(_no_core())
    started = calls.start()
    try:
        answer = await client.request(method, params, timeout=timeout)
    except ExtensionRequestError as exc:
        raise _error(exc, timeout, sends) from exc
    calls.done(log, f"WhatsApp: {method}", started, timeout=timeout)
    return answer


def _error(exc: ExtensionRequestError, timeout: float, sends: bool) -> WhatsAppError:
    maybe = "; it may have gone out already (check before sending again)" if sends else ""
    code = exc.code
    if code == "not_connected":  # it was connected when it asked: the connection dropped on the way
        return WhatsAppError(f"The connection to HiroLeague dropped{maybe}") if sends else WhatsAppNotRunning(_no_core())
    if code == "timeout":
        return WhatsAppError(f"HiroLeague didn't answer in {timeout:.0f} s{maybe}")
    if code == WHATSAPP_ERROR_NOT_RUNNING:
        return WhatsAppNotRunning(f"HiroLeague's WhatsApp isn't running ({WHERE})")
    if code == WHATSAPP_ERROR_NOT_CONNECTED:
        return WhatsAppNotRunning(f"WhatsApp isn't linked or online in HiroLeague ({WHERE})")
    if code == WHATSAPP_ERROR_FAILED:
        return WhatsAppError(f"WhatsApp failed: {exc.message}")
    if code == "invalid_params":
        return WhatsAppError(f"HiroLeague refused the request: {exc.message}")
    return WhatsAppError(f"HiroLeague failed ({code}): {exc.message}")


async def status() -> WhatsAppStatus:
    try:
        s = await _ask(METHOD_WHATSAPP_STATUS, {}, STATUS_TIMEOUT)
    except WhatsAppError as exc:  # not logged: this is the answer (pages and System health poll it), its note says why
        return WhatsAppStatus(state="no_core", note=str(exc), outputs=ext().outputs)
    with translate(WhatsAppError, "HiroLeague's WhatsApp status can't be read"):
        state, note = describe(bool(s["running"]), str(s.get("state") or ""), dict(s.get("detail") or {}),
                               bool(s.get("waiting_for_link")))
        account = str(s.get("account") or "").strip() or None
    return WhatsAppStatus(state=state, account=account, note=note, outputs=ext().outputs)


async def check(numbers: list[str]) -> list[dict[str, Any]]:
    """Which numbers have WhatsApp: [{"query", "on_whatsapp", "jid"}], in the order asked."""
    if len(numbers) > WHATSAPP_CHECK_MAX:
        raise Invalid(f"At most {WHATSAPP_CHECK_MAX} numbers can be checked at once")
    answer = await _ask(METHOD_WHATSAPP_CHECK, {"numbers": numbers}, CHECK_TIMEOUT)
    with translate(WhatsAppError, "HiroLeague's WhatsApp check can't be read"):
        return [{"query": str(a["query"]), "on_whatsapp": bool(a["on_whatsapp"]), "jid": str(a["jid"])}
                for a in answer["answers"]]


async def send(to: str, text: str | None = None, *, image: bytes | None = None,
               voice: bytes | None = None, voice_seconds: float = 0, waveform: bytes = b"") -> bool:
    """Send to a number (digits with country code) or JID. Returns False when OUTPUTS=off.

    image: a JPEG, with `text` as its caption. voice: an OGG/Opus clip (see tts.audio), sent as a voice
    note; voice_seconds and waveform (64 bytes, 0..100) are what WhatsApp shows on it.
    """
    if not ext().outputs:
        log.info("OUTPUTS=off, not sending WhatsApp to %s: %s%s", to, text or "",
                 " [+image]" if image else f" [+voice note {voice_seconds:.1f} s]" if voice else "")
        return False
    params: dict[str, Any] = {"to": to}
    if text:
        params["text"] = text
    if image:
        params["image_b64"] = base64.b64encode(image).decode()
    if voice:
        params |= {"voice_b64": base64.b64encode(voice).decode(), "voice_seconds": voice_seconds,
                   "waveform_b64": base64.b64encode(waveform).decode()}
    answer = await _ask(METHOD_WHATSAPP_SEND, params, SEND_TIMEOUT, sends=True)
    if answer.get("sent") is not True:  # it answered, but not that it sent: it may have, so never "not running"
        raise WhatsAppError("HiroLeague answered without saying the message was sent (check before sending again)")
    return True


NOTIFY_TIMEOUT = 120.0  # seconds: Hiro may write the message and make a voice note before WhatsApp sends it


async def notify(core_person_id: str, name: str, text: str, *, character: bool) -> bool:
    """Ask Hiro to tell one person of HiroLeague's family list (Phase 6: by their core person id; the core finds their
    number and the name it uses). `name` is for the app's own log. Returns False when OUTPUTS=off.

    character: Hiro's character writes it in its own words from `text`; else `text` goes as it is."""
    style = NOTIFY_STYLE_CHARACTER if character else NOTIFY_STYLE_EXACT
    if not ext().outputs:
        log.info("OUTPUTS=off, not asking Hiro to tell %s (%s): %s", name, style, text)
        return False
    params = {"to": [{"person": core_person_id}], "medium": NOTIFY_MEDIUM_WHATSAPP, "text": text, "style": style}
    answer = await _ask(METHOD_NOTIFY, params, NOTIFY_TIMEOUT, sends=True)
    with translate(WhatsAppError, "Hiro's answer can't be read"):
        result = answer["results"][0]
    if result.get("sent") is not True:
        raise WhatsAppError(f"Hiro didn't send it: {result.get('error') or 'no reason given'}")
    return True


def normalize_number(raw: str) -> str:
    """'+20 100 123 4567' or '0020…' -> '201001234567'. Local numbers (no country code) are refused."""
    s = raw.strip()
    digits = "".join(c for c in s if c.isdigit())
    if s.startswith("00"):
        digits = digits[2:]
    elif not s.startswith("+"):
        raise Invalid("Use the international format with +country code, e.g. +20 100 123 4567")
    if not 8 <= len(digits) <= 15:
        raise Invalid("That does not look like a full phone number")
    return digits
