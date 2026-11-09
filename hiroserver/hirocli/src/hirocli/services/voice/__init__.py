"""Voices (Phase 7b): voice profiles spoken into OGG/Opus clips, Gemini's voices and designed voices,
the spoken-clip cache, and counting speech in AI usage.

- ``engine``: speak with a profile (cached), Try it (kept in memory), voice samples, the cache's stats;
- ``gemini_speech`` / ``openai_speech``: the providers' APIs (Gemini's Interactions and Voices APIs);
- ``profiles``: which profile speaks (a use or a named profile), a profile in a line, usage counting;
- ``audio``: PCM → OGG/Opus (PyAV) and WhatsApp's waveform; ``kit``: voices, sound tags, limits, prices.

Keys are the core's providers' (Catalog → Providers). Hiro's own spoken replies still use
``services/tts`` until they move to voice profiles (Phase 7b step 5).
"""

from .engine import Clip, cache_stats, kept, sample, speak, try_it
from .net import VoiceError
from .profiles import NoVoiceProfile, count, extension_rows, line, pick

__all__ = [
    "Clip",
    "NoVoiceProfile",
    "VoiceError",
    "cache_stats",
    "count",
    "extension_rows",
    "kept",
    "line",
    "pick",
    "sample",
    "speak",
    "try_it",
]
