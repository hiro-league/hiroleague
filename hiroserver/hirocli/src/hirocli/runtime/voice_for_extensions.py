"""The core speaks for extensions — the ``voice.speak`` and ``voice.profiles`` requests (Phase 7b).

An extension (HomeHiro first: alerts and the Speak node) asks the core to say something instead of
keeping its own speech keys and voices: ``voice.speak`` names one of the extension's declared voice uses
(``ExtensionInfo.voice_uses``), and the core speaks with the profile picked for ``"<extension>:<use>"``
(or the profile the request names: an alert's or a Speak node's own pick). The answer is an OGG/Opus clip
(base64) with its length and WhatsApp's waveform; the extension plays it (HomeHiro: on the camera speakers)
or sends it as a voice note. The same words in the same voice come from the core's clip cache.

Paid clips are counted in AI usage (kind speech, the extension as the source, with person and label).
Extensions only: the app can't spend the home's speech budget by being connected.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from hiro_channel_sdk.constants import (
    METHOD_VOICE_PROFILES,
    METHOD_VOICE_SPEAK,
    VOICE_ERROR_FAILED,
    VOICE_ERROR_INVALID,
    VOICE_ERROR_NO_PROFILE,
)
from hiro_commons.log import Logger

from ..domain.people import get_person
from ..services import voice
from ..services.voice.kit import MAX_CHARS
from .ai_for_extensions import _caller_name
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused

log = Logger.get("VOICE")

MAX_LABEL = 80


async def handle_voice_speak(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    name = await _caller_name(ctx)
    text, use, profile_id, person_id, label = _params(params)
    if person_id and await asyncio.to_thread(get_person, ctx.workspace_path, person_id) is None:
        raise RequestRefused(VOICE_ERROR_INVALID, f"There's no person {person_id!r} in the family list.")
    prefs = ctx.server_ctx.preferences.current
    use_key = f"{name}:{use}" if use else None
    try:
        pid, profile = voice.pick(prefs, use_key=use_key, profile_id=profile_id)
        clip = await voice.speak(ctx.workspace_path, profile, text, cache_mb=prefs.voice.clip_cache_mb)
    except voice.NoVoiceProfile as exc:
        raise RequestRefused(VOICE_ERROR_NO_PROFILE, exc.message) from exc
    except voice.VoiceError as exc:
        code = VOICE_ERROR_INVALID if exc.status == 400 else VOICE_ERROR_FAILED
        log.warning(f"⚠️ Voice not spoken — {name} · {use or profile_id}", error=exc.message)
        raise RequestRefused(code, exc.message) from exc
    await voice.count(
        ctx.workspace_path, clip, profile_id=pid, profile=profile, source=name, use=use or "speak",
        person_id=person_id, label=label,
    )
    log.info(
        f"✅ Voice spoken — {name} · {use or 'own pick'} · {profile.label}",
        seconds=round(clip.seconds, 1),
        cached=clip.cached,
        cost=clip.cost_usd,
        elapsed_ms=int(clip.took_s * 1000),
    )
    return {
        "ogg_b64": base64.b64encode(clip.ogg).decode("ascii"),
        "seconds": clip.seconds,
        "waveform_b64": base64.b64encode(clip.waveform).decode("ascii"),
        "cached": clip.cached,
        "cost": clip.cost_usd,
        "profile_id": pid,
        "profile_name": profile.label,
        "provider": profile.provider,
        "model": profile.model_name,
        "voice": profile.voice,
    }


def _params(params: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """(text, use, profile, person, label) from the request, or RequestRefused invalid."""
    text = params.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RequestRefused(VOICE_ERROR_INVALID, "text is required.")
    if len(text.strip()) > MAX_CHARS:
        raise RequestRefused(VOICE_ERROR_INVALID, f"Too long: {len(text.strip())} characters, the limit is {MAX_CHARS}.")
    values: list[str] = []
    for key in ("use", "profile", "person", "label"):
        value = params.get(key)
        if value is not None and not isinstance(value, str):
            raise RequestRefused(VOICE_ERROR_INVALID, f"{key} must be text.")
        values.append((value or "").strip())
    use, profile_id, person_id, label = values
    if not use and not profile_id:
        raise RequestRefused(VOICE_ERROR_INVALID, "use or profile is required.")
    if len(label) > MAX_LABEL:
        raise RequestRefused(VOICE_ERROR_INVALID, f"label must be at most {MAX_LABEL} characters.")
    return text, use, profile_id, person_id, label


async def handle_voice_profiles(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    del params
    name = await _caller_name(ctx)
    return voice.extension_rows(ctx.server_ctx.preferences.current, name)


VOICE_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_VOICE_SPEAK, handle_voice_speak, EXTENSIONS_ONLY),
    (METHOD_VOICE_PROFILES, handle_voice_profiles, EXTENSIONS_ONLY),
)
