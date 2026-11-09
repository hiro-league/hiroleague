"""Voice profiles and the uses that point at them (``prefs.voice``, Phase 7b).

A voice profile is a named way to speak: a speech model from the catalog (``google:…-tts``,
``openai:…``), a voice (OpenAI's named voices; Gemini's studio voices, its voice library, or our own
designed voices ``voice_…``), a speaking style in plain words, and a speed (OpenAI only). It is
the speech counterpart of an AI profile (``models_ai.py``).

- ``profiles`` and ``uses`` are edited by the Catalog's Profiles tab (``save_skip``: the Preferences
  page never sends them), like ``ai.profiles`` / ``ai.uses``.
- ``uses``: ``"<extension name>:<use id>"`` → profile id, for the speech uses an extension declares
  (HomeHiro's ``home:speak``). A speak request names a use, or a profile directly (an alert's or a
  Speak node's own pick).
- ``clip_cache_mb``: spoken clips are kept on disk (``<workspace>/data/voice-clips``) so the same
  words in the same voice aren't paid for twice; Preferences → General → Spoken clips. 0 keeps none.

The speaking itself runs in ``services/voice``.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

from .defaults import pref_field

VOICE_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# No dots: a use key is one segment of a preferences PATCH path ("voice.uses.home:speak").
_USE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}:[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
# The providers whose speech the core speaks (catalog provider ids).
VOICE_PROVIDERS: tuple[str, ...] = ("google", "openai")


class VoiceProfile(BaseModel):
    """One voice profile (module notes)."""

    label: str = Field(min_length=1, max_length=80)
    # A catalog speech model, "provider:model" (e.g. google:gemini-3.8-flash-tts).
    model: str
    # OpenAI: a voice name ("sage"); Gemini: a voice id ("kore", "ar-eg-advisor-11", "voice_…").
    voice: str = Field(min_length=1, max_length=128)
    # What the voice is called on the page; kept so a designed voice Google dropped still reads by name.
    voice_label: str = Field(default="", max_length=128)
    # Tone, pace, accent, emotion in plain words; never read aloud (OpenAI instructions, Gemini style).
    style: str = Field(default="", max_length=2000)
    # OpenAI only (Gemini has no speed); 1 = as the voice speaks.
    speed: float = Field(default=1.0, ge=0.25, le=4.0)

    @field_validator("label")
    @classmethod
    def _clean_label(cls, value: str) -> str:
        label = " ".join(value.split())
        if not label:
            raise ValueError("a voice profile needs a name")
        return label

    @field_validator("model")
    @classmethod
    def _model_is_speech(cls, value: str) -> str:
        model = value.strip()
        check_voice_model_id(model)
        return model

    @field_validator("voice")
    @classmethod
    def _clean_voice(cls, value: str) -> str:
        voice = value.strip()
        if not voice:
            raise ValueError("a voice profile needs a voice")
        return voice

    @property
    def provider(self) -> str:
        return self.model.partition(":")[0]

    @property
    def model_name(self) -> str:
        return self.model.partition(":")[2]


def check_voice_model_id(model: str) -> None:
    """Raise ValueError unless ``model`` is a catalog speech model of a provider the core speaks with."""
    provider, sep, name = model.partition(":")
    if not sep or not name.strip():
        raise ValueError(f"model must be provider:model, got {model!r}")
    if provider not in VOICE_PROVIDERS:
        raise ValueError(f"the core speaks with {', '.join(VOICE_PROVIDERS)} models, not {provider!r}")
    from ..model_catalog import get_model_catalog

    spec = get_model_catalog().get_model(model)
    if spec is None:
        raise ValueError(f"model {model!r} is not in the catalog")
    if not spec.supports_kind("tts"):
        raise ValueError(f"model {model!r} is not a speech model (kind={spec.model_kind})")


class VoicePreferences(BaseModel):
    """``prefs.voice``: the voice profiles, which profile each speech use speaks with, and the clip cache."""

    profiles: dict[str, VoiceProfile] = pref_field(save_skip=True, default_factory=dict)
    # "<extension name>:<use id>" → profile id; None = declared, no profile picked yet.
    uses: dict[str, str | None] = pref_field(save_skip=True, default_factory=dict)
    clip_cache_mb: int = pref_field(
        default=200,
        ge=0,
        le=5000,
        title="Keep spoken clips up to (MB)",
        description=(
            "Clips Hiro and the extensions had spoken, kept so the same words in the same voice are not paid "
            "for again. Once full, the oldest go first. 0 keeps none."
        ),
    )

    @model_validator(mode="after")
    def _validate_links(self) -> "VoicePreferences":
        for pid in self.profiles:
            if not VOICE_PROFILE_ID.match(pid):
                raise ValueError(
                    f"voice profile id {pid!r} must be lowercase letters, digits, '-' or '_' (1–64 characters)"
                )
        for key, pid in self.uses.items():
            if not _USE_KEY.match(key):
                raise ValueError(f"voice use {key!r} must be '<extension>:<use id>'")
            if pid is not None and pid not in self.profiles:
                raise ValueError(f"voice use {key!r} points at an unknown profile {pid!r}")
        return self
