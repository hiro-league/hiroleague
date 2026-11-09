"""Speaking with a voice profile (Phase 7b, ported from HomeHiro's ``tts/service.py``).

A voice profile (or an unsaved draft) plus text in, a ready-to-send OGG/Opus clip out:

- ``speak(...)`` is what a speak request uses. Clips are cached on disk under
  ``<workspace>/data/voice-clips`` (``voice.clip_cache_mb``; the oldest go first), so a repeated alert
  costs nothing the second time; the cache keeps what it saved (``cache_stats``).
- ``try_it(...)`` is the admin's Try it: never cached (you want to hear it again), kept in memory a while
  so the page can play it, download it or send it as a WhatsApp voice note.
- ``sample(...)``: a short sample of a Gemini voice (designed voices come with one; prebuilt ones are
  spoken once with Flash-Lite and kept).

Keys come from the core's providers (Catalog → Providers): ``google`` and ``openai``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hiro_commons.constants.storage import DATA_DIR
from hiro_commons.log import Logger

from ...domain.credential_store import CredentialStore
from ...domain.preferences import VoiceProfile
from ...domain.workspace import workspace_id_for_path
from . import audio, gemini_speech, openai_speech
from .kit import MAX_CHARS, Speech, openai_voices
from .net import VoiceError

log = Logger.get("VOICE")

CLIPS_DIR = "voice-clips"
MAX_TRY_CLIPS = 30  # Try it clips kept in memory
SAMPLE_MODEL = "gemini-3.8-flash-lite-tts"  # voice samples: the cheap model is plenty
PROVIDER_NAMES = {"google": "Google", "openai": "OpenAI"}
SAMPLE_TEXT = {
    "en": "Hi, I'm one of the voices you can choose. This is how I sound.",
    "ar": "مرحبا، أنا أحد الأصوات التي يمكنك اختيارها. هكذا يبدو صوتي.",
    "fr": "Bonjour, je suis l'une des voix que vous pouvez choisir. Voici comment je sonne.",
    "es": "Hola, soy una de las voces que puedes elegir. Así es como sueno.",
    "de": "Hallo, ich bin eine der Stimmen, die du wählen kannst. So klinge ich.",
    "it": "Ciao, sono una delle voci che puoi scegliere. Ecco come suono.",
    "pt": "Olá, sou uma das vozes que você pode escolher. É assim que eu soo.",
    "hi": "नमस्ते, मैं उन आवाज़ों में से एक हूँ जिन्हें आप चुन सकते हैं। मेरी आवाज़ ऐसी है।",
    "ja": "こんにちは、選べる声のひとつです。こんな声です。",
    "ko": "안녕하세요, 선택할 수 있는 목소리 중 하나예요. 제 목소리는 이렇습니다.",
}


@dataclass
class Clip:
    ogg: bytes
    seconds: float
    waveform: bytes
    cost_usd: float | None  # None: no price for the model
    cost_exact: bool
    took_s: float = 0.0
    cached: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


_try_clips: OrderedDict[str, Clip] = OrderedDict()


def clips_dir(workspace_path: Path) -> Path:
    return workspace_path / DATA_DIR / CLIPS_DIR


def api_key(workspace_path: Path, provider: str) -> str:
    """The provider's key from the core's credential store, or VoiceError 400 saying where to add it."""
    wid = workspace_id_for_path(workspace_path)
    key = CredentialStore(workspace_path, wid).get_api_key(provider) if wid is not None else None
    if not key:
        name = PROVIDER_NAMES.get(provider, provider)
        raise VoiceError(f"{name}: no API key. Add it under Catalog → Providers.", 400)
    return key


def check(profile: VoiceProfile) -> None:
    """What preferences can't check: an OpenAI voice must be one of OpenAI's (Gemini's are checked by Google)."""
    if profile.provider == "openai" and profile.voice not in openai_voices():
        raise VoiceError(f"OpenAI has no voice {profile.voice!r}", 400)


async def synthesize(workspace_path: Path, profile: VoiceProfile, text: str) -> Speech:
    check(profile)
    said = text.strip()
    if not said:
        raise VoiceError("Nothing to say", 400)
    if len(said) > MAX_CHARS:
        raise VoiceError(f"Too long: {len(said)} characters, the limit is {MAX_CHARS}", 400)
    key = api_key(workspace_path, profile.provider)
    if profile.provider == "openai":
        return await openai_speech.speak(
            said, api_key=key, model=profile.model_name, voice=profile.voice, style=profile.style, speed=profile.speed
        )
    return await gemini_speech.speak(said, api_key=key, model=profile.model_name, voice=profile.voice, style=profile.style)


async def encode(speech: Speech, took: float = 0.0) -> Clip:
    ogg = await asyncio.to_thread(audio.to_ogg_opus, speech.pcm, speech.rate)
    wave = await asyncio.to_thread(audio.waveform, speech.pcm)
    return Clip(
        ogg, speech.seconds, wave, speech.cost_usd, speech.cost_exact, took,
        tokens_in=speech.tokens_in, tokens_out=speech.tokens_out,
    )


# --- Try it ---------------------------------------------------------------------------------------


async def try_it(workspace_path: Path, profile: VoiceProfile, text: str) -> Clip:
    started = time.monotonic()
    speech = await synthesize(workspace_path, profile, text)
    clip = await encode(speech, time.monotonic() - started)
    log.info(
        f"✅ Voice tried — {profile.label} · {profile.model} · {profile.voice}",
        seconds=round(clip.seconds, 1),
        elapsed_ms=int(clip.took_s * 1000),
        cost=clip.cost_usd,
    )
    return keep(clip)


def keep(clip: Clip) -> Clip:
    _try_clips[clip.id] = clip
    while len(_try_clips) > MAX_TRY_CLIPS:
        _try_clips.popitem(last=False)
    return clip


def kept(clip_id: str) -> Clip | None:
    return _try_clips.get(clip_id)


# --- Speaking for extensions, with the clip cache ---------------------------------------------------


def _cache_key(profile: VoiceProfile, text: str) -> str:
    said = {"model": profile.model, "voice": profile.voice, "style": profile.style, "speed": profile.speed}
    return hashlib.sha256(json.dumps([said, text.strip()], sort_keys=True).encode()).hexdigest()


async def speak(workspace_path: Path, profile: VoiceProfile, text: str, *, cache_mb: int) -> Clip:
    """Say ``text`` with ``profile``: from the cache when the same words were said in the same voice."""
    folder = clips_dir(workspace_path)
    key = _cache_key(profile, text)
    ogg_path, meta_path = folder / f"{key}.ogg", folder / f"{key}.json"
    if cache_mb > 0 and ogg_path.exists() and meta_path.exists():
        hit = await asyncio.to_thread(_read_cached, ogg_path, meta_path)
        if hit is not None:
            return hit
    started = time.monotonic()
    speech = await synthesize(workspace_path, profile, text)
    clip = await encode(speech, time.monotonic() - started)
    if cache_mb > 0:
        await asyncio.to_thread(_write_cached, folder, ogg_path, meta_path, clip, profile, text, cache_mb)
    return clip


def _read_cached(ogg_path: Path, meta_path: Path) -> Clip | None:
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        clip = Clip(
            ogg_path.read_bytes(), float(meta["seconds"]), bytes.fromhex(meta["waveform"]), 0.0, True, cached=True
        )
        ogg_path.touch()  # most recently used: pruned last
        _add_saved(ogg_path.parent, float(meta.get("cost_usd") or 0.0))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("⚠️ Voice clip cache — a cached clip can't be read; speaking it again", error=str(exc))
        return None
    return clip


def _write_cached(
    folder: Path, ogg_path: Path, meta_path: Path, clip: Clip, profile: VoiceProfile, text: str, cache_mb: int
) -> None:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        ogg_path.write_bytes(clip.ogg)
        meta = {
            "seconds": clip.seconds,
            "waveform": clip.waveform.hex(),
            "profile": profile.label,
            "text": text.strip(),
            "cost_usd": clip.cost_usd or 0.0,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        _prune(folder, cache_mb * 1024 * 1024)
    except OSError as exc:  # e.g. the disk is full: the clip is paid for and made, so it is still said
        log.warning("⚠️ Voice clip cache — keeping the clip failed", error=str(exc))


def _prune(folder: Path, max_bytes: int) -> None:
    clips = sorted(folder.glob("*.ogg"), key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for f in clips:
        total += f.stat().st_size
        if total > max_bytes:
            f.unlink(missing_ok=True)
            f.with_suffix(".json").unlink(missing_ok=True)


def _stats_path(folder: Path) -> Path:
    return folder / "stats.json"


def _read_stats(folder: Path) -> dict[str, object]:
    try:
        return json.loads(_stats_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _add_saved(folder: Path, cost: float) -> None:
    """A clip said again from the cache: what it would have cost is saved (kept since the first save)."""
    stats = _read_stats(folder)
    stats.setdefault("since", datetime.now(UTC).isoformat())
    stats["hits"] = int(stats.get("hits") or 0) + 1  # type: ignore[call-overload]
    stats["saved_usd"] = float(stats.get("saved_usd") or 0.0) + cost  # type: ignore[arg-type]
    try:
        _stats_path(folder).write_text(json.dumps(stats), encoding="utf-8")
    except OSError as exc:
        log.warning("⚠️ Voice clip cache — the savings count wasn't kept", error=str(exc))


def cache_stats(workspace_path: Path) -> dict[str, object]:
    """What the clip cache holds now and what it saved (for Preferences → General → Spoken clips)."""
    folder = clips_dir(workspace_path)
    clips = list(folder.glob("*.ogg")) if folder.exists() else []
    stats = _read_stats(folder) if folder.exists() else {}
    return {
        "clips": len(clips),
        "bytes": sum(f.stat().st_size for f in clips),
        "hits": int(stats.get("hits") or 0),  # type: ignore[call-overload]
        "saved_usd": float(stats.get("saved_usd") or 0.0),  # type: ignore[arg-type]
        "since": stats.get("since"),
    }


# --- Voice samples --------------------------------------------------------------------------------


def _sample_path(workspace_path: Path, voice_id: str) -> Path:
    return clips_dir(workspace_path) / "samples" / f"{hashlib.sha256(voice_id.encode()).hexdigest()[:24]}.ogg"


async def sample(workspace_path: Path, voice_id: str) -> tuple[bytes, Clip | None]:
    """A short OGG sample of a Gemini voice, and the clip when it was just paid for (to count it)."""
    path = _sample_path(workspace_path, voice_id)
    if path.exists():
        return path.read_bytes(), None
    key = api_key(workspace_path, "google")
    if voice_id.startswith("voice_"):
        _, pcm_rate = await gemini_speech.voice(key, voice_id)
        if pcm_rate is None:
            raise VoiceError("Gemini has no sample for this voice", 404)
        pcm, rate = pcm_rate
        clip = await encode(Speech(pcm, rate, audio.pcm_seconds(pcm, rate), 0.0, True))
        paid = None
    else:
        info = next((v for v in await gemini_speech.voices(key) if v["id"] == voice_id), None)
        if info is None:
            raise VoiceError(f"Gemini has no voice {voice_id!r}", 404)
        lang = (info["language"] or "en").split("-")[0]
        speech = await gemini_speech.speak(SAMPLE_TEXT.get(lang, SAMPLE_TEXT["en"]), api_key=key, model=SAMPLE_MODEL, voice=voice_id)
        clip = paid = await encode(speech)
    remember_sample(workspace_path, voice_id, clip.ogg)
    return clip.ogg, paid


def remember_sample(workspace_path: Path, voice_id: str, ogg: bytes) -> None:
    """Keep a voice's sample. A failure is only logged: the sample is played all the same, made again next time."""
    path = _sample_path(workspace_path, voice_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ogg)
    except OSError as exc:
        log.warning("⚠️ Voice samples — keeping a sample failed", error=str(exc))
