"""Gemini 3.8 speech through the Interactions API, and Gemini's voices (Voices API). Phase 7b, from HomeHiro.

Speech: the text is spoken word for word, sound tags like <sigh> included; the style goes in a separate
``speech_metadata`` annotation. Raw PCM back (24 kHz, 16-bit mono); the cost is exact (usage comes back).

Voices: one list holds about 2,000 prebuilt voices (30 "studio" ones with plain names like "kore", the
rest per language like "ar-eg-advisor-11") and the voices designed on this account ("voice_…", kept by
Google for a year). The whole list is cached for a day per API key and filtered locally.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import time
import wave
from typing import Any

from hiro_commons.log import Logger

from .audio import pcm_seconds, wav_to_pcm
from .kit import Speech, speech_cost
from .net import VoiceError, send

log = Logger.get("VOICE")

BASE = "https://generativelanguage.googleapis.com/v1beta"
CATALOG_TTL_S = 24 * 3600
DESIGN_MODEL = "gemini-3.8-flash-tts"  # a designed voice also works with Flash-Lite
RATES = range(8000, 48001)  # sample rates that make sense for speech; anything else is a misread answer
UNREADABLE = (ValueError, KeyError, TypeError, IndexError, AttributeError, binascii.Error, wave.Error, EOFError)

# Per API key (hashed): (when read, the voices). Designed voices belong to the account.
_voices: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_voices_lock = asyncio.Lock()


def _headers(api_key: str) -> dict[str, str]:
    return {"x-goog-api-key": api_key}


def _key_of(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def _usage_cost(model: str, usage: dict[str, Any]) -> tuple[float | None, int, int]:
    tokens_in = int(usage.get("total_input_tokens") or 0)
    tokens_out = int(usage.get("total_output_tokens") or 0)
    return speech_cost("google", model, text_tokens=tokens_in, audio_tokens=tokens_out), tokens_in, tokens_out


async def speak(text: str, *, api_key: str, model: str, voice: str, style: str = "") -> Speech:
    part: dict[str, Any] = {"type": "text", "text": text}
    if style.strip():
        part["annotations"] = [{"type": "speech_metadata", "style": style.strip()}]
    body = {
        "model": model,
        "input": [{"type": "user_input", "content": [part]}],
        "response_format": {"type": "audio", "mime_type": "audio/l16", "sample_rate": 24000},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    r = await send("POST", f"{BASE}/interactions", provider="Gemini", json=body, headers=_headers(api_key))
    try:
        data = r.json()
        audio = [c for step in data.get("steps", []) for c in step.get("content", []) if c.get("type") == "audio"]
        if not audio:
            raise VoiceError("Gemini: the answer had no audio")
        pcm = b"".join(base64.b64decode(c["data"], validate=True) for c in audio)
        rate = int(audio[0].get("sample_rate") or 24000)
        if rate not in RATES:
            raise ValueError(f"sample rate {rate}")
        cost, tokens_in, tokens_out = _usage_cost(model, data.get("usage") or {})
    except UNREADABLE as exc:
        raise VoiceError(f"Gemini: an answer the core can't read ({type(exc).__name__})") from exc
    return Speech(pcm, rate, pcm_seconds(pcm, rate), cost, cost_exact=True, tokens_in=tokens_in, tokens_out=tokens_out)


# --- Voices ---------------------------------------------------------------------------------------


def source_of(voice_id: str) -> str:
    """studio ("kore"), library ("ar-eg-advisor-11") or mine ("voice_…", designed on this account)."""
    return "mine" if voice_id.startswith("voice_") else "library" if "-" in voice_id else "studio"


def _slim(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": v["id"],
        "name": v.get("display_name") or v["id"],
        "source": source_of(v["id"]),
        "language": v.get("language_code"),
        "accent": v.get("accent"),
        "gender": v.get("gender"),
        "pitch": v.get("pitch"),
        "persona": v.get("persona"),
        "description": v.get("description") or (v.get("prompted") or {}).get("input"),
        "expires": v.get("expire_time"),
    }


async def voices(api_key: str, refresh: bool = False) -> list[dict[str, Any]]:
    """Every voice this account can use: prebuilt ones and its designed ones. Cached for a day."""
    key = _key_of(api_key)
    async with _voices_lock:
        held = _voices.get(key)
        if held is None or refresh or time.monotonic() - held[0] > CATALOG_TTL_S:
            found: list[dict[str, Any]] = []
            token: str | None = None
            while True:
                params = {"page_size": "1000", **({"page_token": token} if token else {})}
                r = await send("GET", f"{BASE}/voices", provider="Gemini", params=params, headers=_headers(api_key))
                try:
                    page = r.json()
                    found += [_slim(v) for v in page.get("voices", [])]
                    token = page.get("next_page_token")
                except UNREADABLE as exc:
                    raise VoiceError(f"Gemini: a voice list the core can't read ({type(exc).__name__})") from exc
                if not token:
                    break
            held = _voices[key] = (time.monotonic(), found)
            log.info(f"✅ Gemini voices read — {len(found)} voices")
        return held[1]


async def voice(api_key: str, voice_id: str) -> tuple[dict[str, Any], tuple[bytes, int] | None]:
    """One designed voice, and its sample as (PCM, rate) when Google has one."""
    r = await send("GET", f"{BASE}/voices/{voice_id}", provider="Gemini", headers=_headers(api_key))
    try:
        data = r.json()
        sample = data.get("sample_audio")
        return _slim(data), wav_to_pcm(base64.b64decode(sample["data"], validate=True)) if sample else None
    except UNREADABLE as exc:
        raise VoiceError(f"Gemini: a voice the core can't read ({type(exc).__name__})") from exc


async def design(
    api_key: str, name: str, description: str, language: str | None, gender: str | None
) -> tuple[dict[str, Any], tuple[bytes, int], float | None]:
    """Make a voice from a description of who is speaking (Google keeps it a year). Takes about 30 s."""
    spec: dict[str, Any] = {
        "model": DESIGN_MODEL,
        "type": "prompted",
        "display_name": name,
        "prompted": {"input": description},
    }
    if language:
        spec["language_code"] = language
    if gender:
        spec["gender"] = gender
    r = await send(
        "POST", f"{BASE}/voices", provider="Gemini", timeout=180, json={"store": True, "voice": spec},
        headers=_headers(api_key),
    )
    try:
        data = r.json()
        designed = (
            _slim(data),
            wav_to_pcm(base64.b64decode(data["sample_audio"]["data"], validate=True)),
            _usage_cost(DESIGN_MODEL, data.get("usage") or {})[0],
        )
    except UNREADABLE as exc:
        raise VoiceError(f"Gemini: a designed voice the core can't read ({type(exc).__name__})") from exc
    await _refresh_voices(api_key)
    return designed


async def delete(api_key: str, voice_id: str) -> None:
    await send("DELETE", f"{BASE}/voices/{voice_id}", provider="Gemini", headers=_headers(api_key))
    await _refresh_voices(api_key)


async def _refresh_voices(api_key: str) -> None:
    """After a design or a delete: that is done (and billed), so a list that can't be read now is no reason
    to report it failed. It is read again when next asked for."""
    try:
        await voices(api_key, refresh=True)
    except VoiceError as exc:
        log.warning("⚠️ Gemini voices — refreshing the list failed", error=exc.message)
        _voices.pop(_key_of(api_key), None)
