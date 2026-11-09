"""Phase 7b: voices — profiles in preferences, the OGG clip, the clip cache, which profile speaks, the speak
request's params, usage counting and the HomeHiro import. Providers are faked: nothing is paid for."""

from __future__ import annotations

import asyncio
import math
import sqlite3
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hirocli.domain.preferences import VoiceProfile, WorkspacePreferences
from hirocli.services import voice
from hirocli.services.ai_usage.store import read_rows
from hirocli.services.voice import audio, engine
from hirocli.services.voice.kit import Speech, strip_tags
from hirocli.services.voice.net import VoiceError

GEMINI = {"label": "Hiro's voice", "model": "google:gemini-3.8-flash-tts", "voice": "kore", "style": "Warm."}
OPENAI = {"label": "Door alert", "model": "openai:gpt-4o-mini-tts", "voice": "sage", "speed": 1.1}


def _tone(seconds: float = 0.5, rate: int = 24000) -> bytes:
    n = int(seconds * rate)
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(n))


def _prefs(**voice_prefs: object) -> WorkspacePreferences:
    return WorkspacePreferences.model_validate({"voice": voice_prefs})


# ── Preferences ─────────────────────────────────────────────────────────────────────────────────


def test_a_profile_needs_a_catalog_speech_model_and_uses_point_at_profiles() -> None:
    p = _prefs(profiles={"hiro": GEMINI, "door": OPENAI}, uses={"home:speak": "door"})
    assert (p.voice.profiles["door"].provider, p.voice.profiles["door"].model_name) == ("openai", "gpt-4o-mini-tts")
    assert p.voice.clip_cache_mb == 200
    with pytest.raises(ValidationError, match="not a speech model"):
        _prefs(profiles={"x": {**GEMINI, "model": "google:gemini-3.8-flash"}})
    with pytest.raises(ValidationError, match="unknown profile"):
        _prefs(profiles={"hiro": GEMINI}, uses={"home:speak": "gone"})
    with pytest.raises(ValidationError, match="must be lowercase"):
        _prefs(profiles={"Hiro Voice": GEMINI})
    with pytest.raises(ValidationError):
        VoiceProfile.model_validate({**OPENAI, "speed": 5})


# ── Audio ───────────────────────────────────────────────────────────────────────────────────────


def test_pcm_becomes_an_ogg_opus_voice_note_with_its_waveform() -> None:
    pcm = _tone(0.5)
    ogg = audio.to_ogg_opus(pcm)
    assert ogg[:4] == b"OggS" and b"OpusHead" in ogg[:200]
    assert len(audio.waveform(pcm)) == audio.WAVEFORM_BARS
    assert audio.pcm_seconds(pcm) == pytest.approx(0.5)


def test_openai_doesnt_hear_geminis_sound_tags() -> None:
    assert strip_tags("Hello <sigh> there <3 <laugh>") == "Hello there <3"


# ── Which profile speaks ─────────────────────────────────────────────────────────────────────────


def test_a_named_profile_wins_over_the_uses_and_none_is_no_profile() -> None:
    prefs = _prefs(profiles={"hiro": GEMINI, "door": OPENAI}, uses={"home:speak": "door", "home:story": None})
    assert voice.pick(prefs, use_key="home:speak", profile_id=None)[0] == "door"
    assert voice.pick(prefs, use_key="home:speak", profile_id="hiro")[0] == "hiro"
    with pytest.raises(voice.NoVoiceProfile):
        voice.pick(prefs, use_key="home:story", profile_id=None)
    with pytest.raises(voice.NoVoiceProfile):
        voice.pick(prefs, use_key=None, profile_id="gone")
    assert voice.line(prefs.voice.profiles["door"]) == "OpenAI · gpt-4o-mini-tts · sage · 1.1×"


def test_an_openai_voice_must_be_one_of_openais() -> None:
    with pytest.raises(VoiceError, match="no voice"):
        engine.check(VoiceProfile.model_validate({**OPENAI, "voice": "kore"}))


# ── The clip cache ───────────────────────────────────────────────────────────────────────────────


def test_the_same_words_in_the_same_voice_come_from_the_cache_and_count_what_they_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    said: list[str] = []

    async def fake_synthesize(path: Path, profile: VoiceProfile, text: str) -> Speech:
        said.append(text)
        return Speech(_tone(0.3), 24000, 0.3, 0.002, True, tokens_in=10, tokens_out=200)

    monkeypatch.setattr(engine, "synthesize", fake_synthesize)
    profile = VoiceProfile.model_validate(GEMINI)
    first = asyncio.run(engine.speak(tmp_path, profile, "Someone is at the door", cache_mb=10))
    again = asyncio.run(engine.speak(tmp_path, profile, "  Someone is at the door ", cache_mb=10))
    other = asyncio.run(engine.speak(tmp_path, profile.model_copy(update={"style": "Brisk."}), "Someone is at the door", cache_mb=10))
    assert said == ["Someone is at the door", "Someone is at the door"]  # the restyled one is said again
    assert (first.cached, again.cached, other.cached) == (False, True, False)
    assert again.ogg == first.ogg and again.cost_usd == 0.0
    stats = engine.cache_stats(tmp_path)
    assert (stats["clips"], stats["hits"]) == (2, 1)
    assert stats["saved_usd"] == pytest.approx(0.002)


def test_a_cache_of_zero_keeps_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_synthesize(path: Path, profile: VoiceProfile, text: str) -> Speech:
        return Speech(_tone(0.2), 24000, 0.2, 0.001, True)

    monkeypatch.setattr(engine, "synthesize", fake_synthesize)
    profile = VoiceProfile.model_validate(GEMINI)
    asyncio.run(engine.speak(tmp_path, profile, "Hi", cache_mb=0))
    assert asyncio.run(engine.speak(tmp_path, profile, "Hi", cache_mb=0)).cached is False
    assert engine.cache_stats(tmp_path)["clips"] == 0


def test_too_long_or_empty_text_is_refused_before_any_call(tmp_path: Path) -> None:
    profile = VoiceProfile.model_validate(GEMINI)
    with pytest.raises(VoiceError, match="Nothing to say"):
        asyncio.run(engine.synthesize(tmp_path, profile, "   "))
    with pytest.raises(VoiceError, match="Too long"):
        asyncio.run(engine.synthesize(tmp_path, profile, "a" * 4097))


def test_no_key_says_where_to_add_it(tmp_path: Path) -> None:
    with pytest.raises(VoiceError, match="Catalog → Providers") as info:
        asyncio.run(engine.synthesize(tmp_path, VoiceProfile.model_validate(GEMINI), "Hello"))
    assert info.value.status == 400


# ── Counting ─────────────────────────────────────────────────────────────────────────────────────


def test_a_paid_clip_is_counted_as_speech_and_a_cached_one_isnt(tmp_path: Path) -> None:
    profile = VoiceProfile.model_validate(OPENAI)
    paid = engine.Clip(b"OggS", 1.0, b"", 0.003, False, took_s=1.2, tokens_in=5)
    asyncio.run(voice.count(tmp_path, paid, profile_id="door", profile=profile, source="home", use="speak", label="Front door"))
    asyncio.run(voice.count(tmp_path, engine.Clip(b"OggS", 1.0, b"", 0.0, True, cached=True), profile_id="door",
                            profile=profile, source="home", use="speak"))
    unpriced = engine.Clip(b"OggS", 1.0, b"", None, False)
    asyncio.run(voice.count(tmp_path, unpriced, profile_id="door", profile=profile, source="home", use="speak"))
    rows = read_rows(tmp_path, datetime.now(UTC) - timedelta(hours=2), datetime.now(UTC) + timedelta(hours=1))
    by_label = {r["label"]: r for r in rows}
    row = by_label["Front door"]
    assert (row["kind"], row["source"], row["use_id"], row["profile_id"], row["provider"], row["model"]) == (
        "speech", "home", "speak", "door", "openai", "gpt-4o-mini-tts",
    )
    assert (row["requests"], row["ms"], row["cost"]) == (1, 1200, pytest.approx(0.003))
    assert by_label[""]["unpriced"] == 1 and by_label[""]["requests"] == 1  # the cached clip added nothing


# ── The speak request's params ───────────────────────────────────────────────────────────────────


def test_the_speak_request_needs_text_and_a_use_or_a_profile() -> None:
    from hirocli.runtime.request_handler import RequestRefused
    from hirocli.runtime.voice_for_extensions import _params

    assert _params({"text": " Hi ", "use": "speak", "label": "Front door"}) == (" Hi ", "speak", "", "", "Front door")
    for bad in ({"use": "speak"}, {"text": "Hi"}, {"text": "Hi", "use": 3}, {"text": "a" * 4097, "use": "speak"},
                {"text": "Hi", "use": "speak", "label": "x" * 81}):
        with pytest.raises(RequestRefused):
            _params(bad)


# ── The HomeHiro import ──────────────────────────────────────────────────────────────────────────


def test_homehiros_tts_profiles_become_voice_profiles_with_their_old_ids(tmp_path: Path) -> None:
    from hirocli.services.voice.import_homehiro import read_plan

    db = tmp_path / "homehiro.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE ttsprofile (id TEXT, name TEXT, provider TEXT, model TEXT, voice_id TEXT, "
                     "voice_label TEXT, style TEXT, options TEXT)")
        conn.executemany("INSERT INTO ttsprofile VALUES (?,?,?,?,?,?,?,?)", [
            ("a1", "Door alert", "openai", "gpt-4o-mini-tts-2025-12-15", "sage", "sage", "Brisk.", '{"speed": 1.15}'),
            ("b2", "Hiro", "gemini", "gemini-3.8-flash-tts", "voice_abc", "Hiro", "Warm.", "{}"),
            ("c3", "Broken", "gemini", "gemini-2-tts", "kore", "Kore", "", "{}"),
        ])
    plan = read_plan(db)
    assert set(plan.profiles) == {"hh-a1", "hh-b2"}
    assert (plan.profiles["hh-a1"]["model"], plan.profiles["hh-a1"]["speed"]) == ("openai:gpt-4o-mini-tts", 1.15)
    assert (plan.profiles["hh-b2"]["model"], plan.profiles["hh-b2"]["voice"]) == ("google:gemini-3.8-flash-tts", "voice_abc")
    assert any("Broken" in n for n in plan.notes) and any("2025-12-15" in n for n in plan.notes)
