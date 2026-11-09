"""Voice profiles as callers use them (Phase 7b): which profile speaks, a profile in one line, and counting
what was spoken in the core's AI usage.
"""

from __future__ import annotations

from pathlib import Path

from ...domain.preferences import VoiceProfile, WorkspacePreferences
from ..ai_usage import UsageCall, record_async
from .engine import Clip
from .net import VoiceError

NO_PROFILE = "no_profile"


class NoVoiceProfile(VoiceError):
    """No profile given, and none picked for the use (the speak request answers ``no_profile``)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, 404)


def pick(prefs: WorkspacePreferences, *, use_key: str | None, profile_id: str | None) -> tuple[str, VoiceProfile]:
    """The profile that speaks: the one named (an alert's or a Speak node's own pick), else the use's."""
    pid = (profile_id or "").strip() or (prefs.voice.uses.get(use_key) if use_key else None)
    if not pid:
        what = f"the voice use {use_key!r}" if use_key else "this"
        raise NoVoiceProfile(f"No voice profile for {what}: pick one on the Catalog's Profiles → Uses tab.")
    profile = prefs.voice.profiles.get(pid)
    if profile is None:
        raise NoVoiceProfile(f"There's no voice profile {pid!r}.")
    return pid, profile


def line(profile: VoiceProfile) -> str:
    """"Google · gemini-3.8-flash-tts · Kore · 1.1×" — a profile at a glance."""
    provider = {"google": "Google", "openai": "OpenAI"}.get(profile.provider, profile.provider)
    speed = f" · {profile.speed:g}×" if profile.provider == "openai" and profile.speed != 1 else ""
    return f"{provider} · {profile.model_name} · {profile.voice_label or profile.voice}{speed}"


def extension_rows(prefs: WorkspacePreferences, extension_name: str) -> dict[str, object]:
    """What ``voice.profiles`` answers an extension: every profile in a line, and its uses' picks."""
    prefix = f"{extension_name}:"
    return {
        "profiles": [{"id": pid, "name": p.label, "line": line(p)} for pid, p in prefs.voice.profiles.items()],
        "uses": {k[len(prefix):]: v for k, v in prefs.voice.uses.items() if k.startswith(prefix)},
    }


async def count(
    workspace_path: Path,
    clip: Clip,
    *,
    profile_id: str,
    profile: VoiceProfile,
    source: str,
    use: str,
    person_id: str = "",
    label: str = "",
) -> None:
    """Count a paid clip in AI usage (kind speech). A clip from the cache cost nothing and isn't counted."""
    if clip.cached:
        return
    await record_async(
        workspace_path,
        UsageCall(
            kind="speech",
            source=source,
            use=use,
            profile_id=profile_id,
            profile_name=profile.label,
            provider=profile.provider,
            model=profile.model_name,
            billing="api",
            person_id=person_id,
            label=label,
            tokens_in=clip.tokens_in,
            tokens_out=clip.tokens_out,
            ms=int(clip.took_s * 1000),
            cost=clip.cost_usd or 0.0,
            unpriced=int(clip.cost_usd is None),
        ),
    )
