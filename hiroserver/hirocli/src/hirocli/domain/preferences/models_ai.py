"""AI profiles and the uses that point at them (``prefs.ai``, Phase 7a).

An AI profile is a named way to ask a model a question: which model, how hard it thinks, extra
instructions, its limits (dollars a day, asks an hour, how many at once) and a fallback profile to
ask instead when it can't answer. Extensions declare their *uses* (HomeHiro: "Ask a camera",
"Wake word check", …); the admin points each use at a profile in ``ai.uses``, keyed
``"<extension name>:<use id>"``.

Stored like ``image_profiles``: ``preferences.json``, edited by its own admin page through the
preferences API (``ai`` is ``save_skip`` so the Preferences page never sends it). The ask itself
runs in ``services/ai_ask``. Contract: ``docs/phase7a-ai-asks-design.md``.

Model ids are catalog ids (``provider:model``):

- API providers must name a catalog chat model;
- local servers (catalog providers hosted ``local``: ``lm_studio:*``, ``ollama:*``) may name any
  model the server reports — the server can be off while preferences load, so only the form is
  checked here and the ask checks the server's list;
- plan tools (``claude_code:*``, ``codex:*``, Part B) likewise name the model as the tool reports it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

from .defaults import ThinkingLevel, pref_field

# Fallbacks after the profile itself (contract: "chain ≤ 3 after the profile itself").
AI_MAX_FALLBACKS = 3
# Plan tools: command-line tools signed in with the owner's plan (Part B wires them).
AI_PLAN_PROVIDERS: tuple[str, ...] = ("claude_code", "codex")

AI_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# No dots: a use key is one segment of a preferences PATCH path ("ai.uses.home:ask").
_USE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}:[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class AiProfile(BaseModel):
    """One AI profile (see the module notes)."""

    label: str = Field(min_length=1, max_length=80, title="Name")
    model: str = Field(min_length=3, title="Model", description="Catalog id, provider:model")
    thinking: ThinkingLevel | None = None
    # None = the default (0.7 temperature, 8192 max tokens) when asked or built for one of Hiro's jobs.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    num_ctx: int | None = Field(default=None, ge=256, description="Local models only")
    instructions: str = Field(default="", max_length=8000, description="Appended to every question")
    max_cost_day: float | None = Field(default=None, gt=0, description="USD a day (API models)")
    max_per_hour: int | None = Field(default=None, ge=1, description="Asks an hour (plan and local models)")
    at_once: int = Field(default=1, ge=1, le=4)
    fallback: str | None = None
    # Phase 7b step 5: the job (``jobs.JOB_PRESETS`` id: "chat", "memory", …) this profile was made for
    # as its default, so the admin shows "Default", hides Delete and offers Restore default (which
    # resets the tuning to the job's preset). None = a profile the owner made.
    preset: str | None = None

    @field_validator("model")
    @classmethod
    def _model_resolves(cls, value: str) -> str:
        model = value.strip()
        check_ai_model_id(model)
        return model

    @field_validator("fallback")
    @classmethod
    def _blank_fallback_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("preset")
    @classmethod
    def _preset_is_a_job(cls, value: str | None) -> str | None:
        preset = (value or "").strip() or None
        if preset is not None:
            from .jobs import JOB_PRESETS

            if preset not in JOB_PRESETS:
                raise ValueError(f"preset {preset!r} isn't one of Hiro's jobs ({', '.join(JOB_PRESETS)})")
        return preset

    @property
    def is_plan(self) -> bool:
        """A plan tool's model (claude_code:* / codex:*): askable, but not a LangChain chat model."""
        return self.model.partition(":")[0] in AI_PLAN_PROVIDERS


def check_ai_model_id(model: str) -> None:
    """Raise ValueError unless ``model`` is a model an AI profile may name (module notes)."""
    provider, sep, name = model.partition(":")
    if not sep or not provider or not name.strip():
        raise ValueError(f"model must be provider:model, got {model!r}")
    if provider in AI_PLAN_PROVIDERS:
        return
    from ..model_catalog import get_model_catalog

    cat = get_model_catalog()
    prov = cat.get_provider(provider)
    if prov is None:
        raise ValueError(f"unknown provider {provider!r} in model {model!r}")
    if prov.hosting == "local":
        return  # a model the local server reports (discovered), catalog row or not
    spec = cat.get_model(model)
    if spec is None:
        raise ValueError(f"model {model!r} is not in the catalog")
    if not spec.supports_kind("chat"):
        raise ValueError(f"model {model!r} is not a chat model (kind={spec.model_kind})")


def ai_fallback_chain(profiles: dict[str, AiProfile], profile_id: str) -> list[str]:
    """``profile_id`` then its fallbacks in order (stops at a missing id or a repeat)."""
    chain: list[str] = []
    current: str | None = profile_id
    while current and current not in chain and current in profiles:
        chain.append(current)
        current = profiles[current].fallback
    return chain


# Local server kinds with per-server settings (one address each, kept in the credential store).
AI_LOCAL_SERVER_KINDS: tuple[str, ...] = ("lm_studio", "ollama")


class LocalServerSettings(BaseModel):
    """How the core loads models on a local server (Part B, ported from HomeHiro's ModelSetup)."""

    # A model the core loaded is unloaded after this long without an ask (LM Studio has no idle
    # timer of its own on a load; Ollama's keep_alive is overridden the same way).
    unload_idle_min: int = Field(default=60, ge=1, le=24 * 60)
    # What the core loads a model with (LM Studio) when the profile sets no num_ctx; a picture needs
    # a batch at least its size (Gemma 4 crashed on a picture with a hand-loaded small batch).
    context: int = Field(default=16384, ge=2048, le=262144)
    batch: int = Field(default=2048, ge=64, le=16384)


class AiPreferences(BaseModel):
    """``prefs.ai``: the profiles and which profile each extension use asks."""

    # save_skip on each leaf too: the admin field map lists ai.profiles / ai.uses as their own paths,
    # and the Preferences page must skip them (the Catalog's AI tabs edit them), like image_profiles.
    profiles: dict[str, AiProfile] = pref_field(save_skip=True, default_factory=dict)
    # "<extension name>:<use id>" → profile id; None = declared, no profile picked yet.
    uses: dict[str, str | None] = pref_field(save_skip=True, default_factory=dict)
    # Part B: per local server kind (lm_studio / ollama); a kind not listed uses the defaults.
    local_servers: dict[str, LocalServerSettings] = pref_field(save_skip=True, default_factory=dict)
    # "<extension name>" → the folders (absolute paths) its asks may name for a plan tool to read, with a use
    # that declares ``folder``. An extension not listed may name none. Set in the preferences file for now.
    folders: dict[str, list[str]] = pref_field(save_skip=True, default_factory=dict)

    def local_server(self, kind: str) -> LocalServerSettings:
        return self.local_servers.get(kind) or LocalServerSettings()

    @model_validator(mode="after")
    def _validate_links(self) -> "AiPreferences":
        for pid, profile in self.profiles.items():
            if not AI_PROFILE_ID.match(pid):
                raise ValueError(
                    f"AI profile id {pid!r} must be lowercase letters, digits, '-' or '_' (1–64 characters)"
                )
            if profile.fallback is None:
                continue
            if profile.fallback == pid:
                raise ValueError(f"AI profile {pid!r} can't fall back to itself")
            if profile.fallback not in self.profiles:
                raise ValueError(f"AI profile {pid!r} falls back to an unknown profile {profile.fallback!r}")
        for pid in self.profiles:
            _check_chain(self.profiles, pid)
        for kind in self.local_servers:
            if kind not in AI_LOCAL_SERVER_KINDS:
                raise ValueError(f"ai.local_servers: {kind!r} isn't a local server kind ({', '.join(AI_LOCAL_SERVER_KINDS)})")
        for key, pid in self.uses.items():
            if not _USE_KEY.match(key):
                raise ValueError(f"AI use {key!r} must be '<extension>:<use id>'")
            if pid is not None and pid not in self.profiles:
                raise ValueError(f"AI use {key!r} points at an unknown profile {pid!r}")
        return self


def _check_chain(profiles: dict[str, AiProfile], profile_id: str) -> None:
    """No loops, and at most AI_MAX_FALLBACKS fallbacks after the profile itself."""
    seen = [profile_id]
    current = profiles[profile_id].fallback
    while current is not None:
        if current in seen:
            path = " → ".join([*seen, current])
            raise ValueError(f"AI profile fallbacks loop: {path}")
        seen.append(current)
        if len(seen) - 1 > AI_MAX_FALLBACKS:
            raise ValueError(
                f"AI profile {profile_id!r} has more than {AI_MAX_FALLBACKS} fallbacks: {' → '.join(seen)}"
            )
        current = profiles[current].fallback
