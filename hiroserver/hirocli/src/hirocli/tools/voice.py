"""Voice tools (Phase 7b) — what the Catalog's Voice profiles tab, ``hiro voice …`` and HTTP call.

Voice profiles themselves are created, changed and deleted through the preferences API
(``voice.profiles``, like ``ai.profiles``); these tools read them, and work with voices:

- ``voice_profiles_list`` — the profiles, each with whether its voice still exists at Google;
- ``voice_catalog`` — the speech models, OpenAI's voices, Gemini's sound tags, the length limit, which keys are set;
- ``voice_voices`` — Gemini's voices (studio, library, ours), filtered, with the languages and their counts;
- ``voice_design`` / ``voice_add`` / ``voice_delete`` — our own Gemini voices;
- ``voice_try`` — Try it: speak a text with a saved profile or a draft (kept a while for the page);
- ``voice_uses_list`` / ``voice_uses_set`` — the voice uses extensions declare and their picks;
- ``voice_clip_cache`` — what the spoken-clip cache holds and saved.

Paid speech (Try it, designing, samples) is counted in AI usage under ``hiro``.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger
from pydantic import ValidationError

from ..domain.preferences import VoiceProfile
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam

log = Logger.get("TOOL.VOICE")

DRAFT_ID = "__draft__"
DESIGN_LANGUAGES = ("en-US", "en-GB", "ar-001", "ar-EG", "fr-FR", "es-ES", "de-DE")
VOICE_SOURCES = ("studio", "library", "mine")


def _workspace(workspace: str | None) -> tuple[str, Path]:
    entry, _ = resolve_workspace(workspace)
    return entry.id, Path(entry.path)


def _prefs(workspace_path: Path) -> Any:
    from ..runtime.preferences_runtime import preferences_runtime_for

    return preferences_runtime_for(workspace_path).current


def _write_prefs(workspace_path: Path, edits: dict[str, Any]) -> None:
    from ..runtime.preferences_runtime import preferences_runtime_for

    preferences_runtime_for(workspace_path).update_many(edits)


def _gemini_key(workspace_path: Path) -> str:
    from ..services.voice.engine import api_key

    return api_key(workspace_path, "google")


def _clip_out(clip: Any) -> dict[str, Any]:
    return {
        "id": clip.id,
        "seconds": round(clip.seconds, 2),
        "bytes": len(clip.ogg),
        "took_s": round(clip.took_s, 2),
        "cost_usd": clip.cost_usd,
        "cost_exact": clip.cost_exact,
    }


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class VoiceProfilesResult:
    profiles: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class VoiceCatalogResult:
    models: list[dict[str, Any]] = field(default_factory=list)
    openai_voices: list[str] = field(default_factory=list)
    common_tags: list[str] = field(default_factory=list)
    tag_groups: dict[str, list[str]] = field(default_factory=dict)
    max_chars: int = 0
    design_languages: list[str] = field(default_factory=list)


@dataclass
class VoiceVoicesResult:
    voices: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    languages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class VoiceDesignResult:
    voice: dict[str, Any] = field(default_factory=dict)
    clip: dict[str, Any] = field(default_factory=dict)


@dataclass
class VoiceDoneResult:
    voice_id: str = ""
    done: bool = True


@dataclass
class VoiceTryResult:
    clip: dict[str, Any] = field(default_factory=dict)


@dataclass
class VoiceUsesResult:
    extensions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class VoiceUseSetResult:
    key: str = ""
    profile_id: str | None = None


@dataclass
class VoiceClipCacheResult:
    clips: int = 0
    bytes: int = 0
    hits: int = 0
    saved_usd: float = 0.0
    since: str | None = None
    max_mb: int = 0


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class VoiceProfilesListTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "voice_profiles_list"
    description = "List the voice profiles: model, voice, style, speed, what uses each, and whether its voice still exists"
    params = {"workspace": ToolParam(str, "Workspace name (default: registry default)", required=False)}

    def execute(self, workspace: str | None = None) -> VoiceProfilesResult:
        return asyncio.run(self.execute_async(workspace=workspace))

    async def execute_async(self, workspace: str | None = None) -> VoiceProfilesResult:
        from ..services.voice import VoiceError, gemini_speech, line

        _wid, path = _workspace(workspace)
        prefs = await asyncio.to_thread(_prefs, path)
        known: set[str] | None = None
        if any(p.provider == "google" for p in prefs.voice.profiles.values()):
            try:
                known = {v["id"].lower() for v in await gemini_speech.voices(_gemini_key(path))}
            except VoiceError as exc:  # the list shows without the check
                log.warning("⚠️ Voice profiles — Gemini's voices unreadable; not checked", error=exc.message)
        used_by: dict[str, list[str]] = {}
        for key, pid in prefs.voice.uses.items():
            if pid:
                used_by.setdefault(pid, []).append(key)
        rows = []
        for pid, p in prefs.voice.profiles.items():
            voice_ok = None if p.provider != "google" or known is None else p.voice.lower() in known
            rows.append(
                {"id": pid, **p.model_dump(), "provider": p.provider, "line": line(p), "voice_ok": voice_ok,
                 "used_by": used_by.get(pid, [])}
            )
        return VoiceProfilesResult(profiles=rows)


class VoiceCatalogTool(Tool):
    surfaces = frozenset({"http"})
    name = "voice_catalog"
    description = "What a voice profile can use: speech models (with whether the provider's key is set), OpenAI's voices, sound tags"
    params = {"workspace": ToolParam(str, "Workspace name (default: registry default)", required=False)}

    def execute(self, workspace: str | None = None) -> VoiceCatalogResult:
        from ..domain.credential_store import CredentialStore
        from ..domain.model_catalog import get_model_catalog
        from ..domain.preferences import VOICE_PROVIDERS
        from ..services.voice.kit import COMMON_TAGS, MAX_CHARS, TAG_GROUPS, openai_voices

        wid, path = _workspace(workspace)
        store = CredentialStore(path, wid)
        models = []
        for m in get_model_catalog().list_models(model_kind="tts"):
            provider = m.id.partition(":")[0]
            if provider in VOICE_PROVIDERS:
                models.append(
                    {"id": m.id, "provider": provider, "name": m.display_name or m.id, "key_set": store.is_configured(provider)}
                )
        return VoiceCatalogResult(
            models=models,
            openai_voices=openai_voices(),
            common_tags=list(COMMON_TAGS),
            tag_groups={k: list(v) for k, v in TAG_GROUPS.items()},
            max_chars=MAX_CHARS,
            design_languages=list(DESIGN_LANGUAGES),
        )


class VoiceVoicesTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "voice_voices"
    description = "Gemini's voices: studio, library (about 2,000) or our own designed ones, filtered by language, gender and words"
    params = {
        "source": ToolParam(str, "studio, library or mine (default: all)", required=False),
        "language": ToolParam(str, "A language code, e.g. ar-EG (library)", required=False),
        "gender": ToolParam(str, "female or male", required=False),
        "q": ToolParam(str, "Words to look for (name, accent, persona, description, language)", required=False),
        "limit": ToolParam(int, "How many to return (default 60)", required=False),
        "refresh": ToolParam(bool, "Read the list from Google again", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, **kwargs: Any) -> VoiceVoicesResult:
        return asyncio.run(self.execute_async(**kwargs))

    async def execute_async(
        self,
        source: str | None = None,
        language: str | None = None,
        gender: str | None = None,
        q: str | None = None,
        limit: int | None = None,
        refresh: bool = False,
        workspace: str | None = None,
    ) -> VoiceVoicesResult:
        from ..services.voice import gemini_speech

        _wid, path = _workspace(workspace)
        everything = await gemini_speech.voices(_gemini_key(path), refresh=bool(refresh))
        pool = [v for v in everything if not source or v["source"] == source]
        langs = Counter(v["language"] for v in pool if v.get("language"))
        found = [v for v in pool if _matches(v, language, gender, q)]
        return VoiceVoicesResult(
            voices=found[: max(1, int(limit or 60))],
            total=len(found),
            languages=[{"code": code, "count": n} for code, n in sorted(langs.items())],
        )


def _matches(v: dict[str, Any], language: str | None, gender: str | None, q: str | None) -> bool:
    if language and (v.get("language") or "").lower() != language.lower():
        return False
    if gender and (v.get("gender") or "").lower() != gender.lower():
        return False
    if q:
        hay = " ".join(str(v.get(k) or "") for k in ("name", "id", "accent", "persona", "description", "language")).lower()
        return all(word in hay for word in q.lower().split())
    return True


class VoiceDesignTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "voice_design"
    description = (
        "Design a Gemini voice from a description of who is speaking (about 2¢, about 30 s; Google keeps it a year). "
        "Answers the voice and a sample clip"
    )
    params = {
        "name": ToolParam(str, "The voice's name, e.g. Grandpa"),
        "description": ToolParam(str, "Who is speaking: age, gender, accent, what the voice sounds like"),
        "language": ToolParam(str, "A language code, e.g. ar-EG", required=False),
        "gender": ToolParam(str, "female or male", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, **kwargs: Any) -> VoiceDesignResult:
        return asyncio.run(self.execute_async(**kwargs))

    async def execute_async(
        self,
        name: str,
        description: str,
        language: str | None = None,
        gender: str | None = None,
        workspace: str | None = None,
    ) -> VoiceDesignResult:
        from ..services.ai_usage import HIRO_SOURCE, UsageCall, record_async
        from ..services.voice import VoiceError, gemini_speech
        from ..services.voice.engine import encode, keep, remember_sample
        from ..services.voice.kit import Speech

        _wid, path = _workspace(workspace)
        name, description = " ".join((name or "").split()), (description or "").strip()
        if not 1 <= len(name) <= 80:
            raise VoiceError("A voice needs a name of 1 to 80 characters.", 400)
        if not 10 <= len(description) <= 2000:
            raise VoiceError("Say who is speaking in 10 to 2,000 characters.", 400)
        if gender and gender not in ("female", "male"):
            raise VoiceError("gender must be female or male.", 400)
        voice, (pcm, rate), cost = await gemini_speech.design(_gemini_key(path), name, description, language or None, gender or None)
        clip = keep(await encode(Speech(pcm, rate, len(pcm) / 2 / rate, cost, True)))
        remember_sample(path, voice["id"], clip.ogg)
        await record_async(
            path,
            UsageCall(kind="speech", source=HIRO_SOURCE, use="design_voice", provider="google",
                      model=gemini_speech.DESIGN_MODEL, label=name, cost=cost or 0.0, unpriced=int(cost is None)),
        )
        log.info(f"✅ Voice designed — {name}", voice_id=voice["id"], cost=cost)
        return VoiceDesignResult(voice=voice, clip=_clip_out(clip))


class VoiceAddTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "voice_add"
    description = "Add a voice designed in Google AI Studio by its id (voice_…) to our voices"
    params = {
        "voice_id": ToolParam(str, "The voice id, voice_…"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, **kwargs: Any) -> VoiceDoneResult:
        return asyncio.run(self.execute_async(**kwargs))

    async def execute_async(self, voice_id: str, workspace: str | None = None) -> VoiceDoneResult:
        from ..services.voice import VoiceError, gemini_speech

        _wid, path = _workspace(workspace)
        vid = (voice_id or "").strip()
        if not vid.startswith("voice_"):
            raise VoiceError("A designed voice's id starts with voice_.", 400)
        key = _gemini_key(path)
        await gemini_speech.voice(key, vid)  # VoiceError 404 when this account has no such voice
        await gemini_speech.voices(key, refresh=True)
        log.info("✅ Voice added from AI Studio", voice_id=vid)
        return VoiceDoneResult(voice_id=vid)


class VoiceDeleteTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "voice_delete"
    description = "Delete one of our designed voices at Google (refused while a voice profile uses it). Can't be undone"
    params = {
        "voice_id": ToolParam(str, "The voice id, voice_…"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, **kwargs: Any) -> VoiceDoneResult:
        return asyncio.run(self.execute_async(**kwargs))

    async def execute_async(self, voice_id: str, workspace: str | None = None) -> VoiceDoneResult:
        from ..services.voice import VoiceError, gemini_speech

        _wid, path = _workspace(workspace)
        vid = (voice_id or "").strip()
        if not vid.startswith("voice_"):
            raise VoiceError("Only our own designed voices (voice_…) can be deleted.", 400)
        prefs = await asyncio.to_thread(_prefs, path)
        using = [p.label for p in prefs.voice.profiles.values() if p.voice == vid]
        if using:
            raise VoiceError(f"Used by {', '.join(using)}: pick another voice there first.", 409)
        await gemini_speech.delete(_gemini_key(path), vid)
        log.info("✅ Voice deleted at Google", voice_id=vid)
        return VoiceDoneResult(voice_id=vid)


class VoiceTryTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "voice_try"
    description = "Try a voice profile: speak a text with a saved profile or a draft (kept a while to play, download or send)"
    params = {
        "text": ToolParam(str, "What to say (Gemini's sound tags like <sigh> are spoken)"),
        "profile_id": ToolParam(str, "A saved voice profile id (or give draft)", required=False),
        "draft": ToolParam(str, "A profile not saved yet, as JSON (voice profile fields)", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, **kwargs: Any) -> VoiceTryResult:
        return asyncio.run(self.execute_async(**kwargs))

    async def execute_async(
        self,
        text: str,
        profile_id: str | None = None,
        draft: str | dict[str, Any] | None = None,
        workspace: str | None = None,
    ) -> VoiceTryResult:
        from ..services import voice

        _wid, path = _workspace(workspace)
        pid, profile = await asyncio.to_thread(_tried_profile, path, profile_id, draft)
        clip = await voice.try_it(path, profile, text)
        await voice.count(path, clip, profile_id="" if pid == DRAFT_ID else pid, profile=profile, source="hiro", use="try_it")
        return VoiceTryResult(clip=_clip_out(clip))


def _tried_profile(path: Path, profile_id: str | None, draft: str | dict[str, Any] | None) -> tuple[str, VoiceProfile]:
    from ..services.voice import VoiceError

    if draft:
        try:
            data = json.loads(draft) if isinstance(draft, str) else draft
            return DRAFT_ID, VoiceProfile.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise VoiceError(f"draft isn't a valid voice profile: {exc}", 400) from exc
    pid = (profile_id or "").strip()
    profile = _prefs(path).voice.profiles.get(pid)
    if profile is None:
        raise VoiceError(f"There's no voice profile {pid!r}.", 404)
    return pid, profile


class VoiceUsesListTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "voice_uses_list"
    description = "List each extension's voice uses (what it asks the core to say) and the voice profile each speaks with"
    params = {"workspace": ToolParam(str, "Workspace name (default: registry default)", required=False)}

    def execute(self, workspace: str | None = None) -> VoiceUsesResult:
        from ..domain.extensions import list_paired_extensions

        _wid, path = _workspace(workspace)
        uses = _prefs(path).voice.uses
        out: list[dict[str, Any]] = []
        named: set[str] = set()
        for ext in list_paired_extensions(path):
            named.add(ext.name)
            rows = []
            declared = set()
            for use in ext.declared_voice_uses():
                key = f"{ext.name}:{use['id']}"
                declared.add(key)
                rows.append({"key": key, "id": use["id"], "name": str(use.get("name") or use["id"]),
                             "profile_id": uses.get(key), "status": "ok"})
            for key, pid in sorted(uses.items()):
                if key.startswith(f"{ext.name}:") and key not in declared:
                    rows.append({"key": key, "id": key.partition(":")[2], "name": key.partition(":")[2],
                                 "profile_id": pid, "status": "removed"})
            out.append({"extension": ext.name, "uses": rows})
        for key, pid in sorted(uses.items()):
            ext_name, _, use_id = key.partition(":")
            if ext_name not in named:
                out.append({"extension": ext_name, "uses": [
                    {"key": key, "id": use_id, "name": use_id, "profile_id": pid, "status": "removed"}]})
        return VoiceUsesResult(extensions=out)


class VoiceUsesSetTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "voice_uses_set"
    description = "Point an extension's voice use (e.g. home:speak) at a voice profile, or clear its pick"
    params = {
        "key": ToolParam(str, "The use, '<extension>:<use id>' (e.g. home:speak)"),
        "profile_id": ToolParam(str, "The voice profile id; empty to clear the pick", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, key: str, profile_id: str | None = None, workspace: str | None = None) -> VoiceUseSetResult:
        _wid, path = _workspace(workspace)
        use_key = key.strip()
        pid = (profile_id or "").strip() or None
        _write_prefs(path, {f"voice.uses.{use_key}": pid})  # validated by VoicePreferences
        log.info(f"✅ Voice use set — {use_key} · {pid or 'no profile'}")
        return VoiceUseSetResult(key=use_key, profile_id=pid)


class VoiceClipCacheTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "voice_clip_cache"
    description = "What the spoken-clip cache holds (clips, size) and what it saved since it started"
    params = {"workspace": ToolParam(str, "Workspace name (default: registry default)", required=False)}

    def execute(self, workspace: str | None = None) -> VoiceClipCacheResult:
        from ..services.voice import cache_stats

        _wid, path = _workspace(workspace)
        stats = cache_stats(path)
        return VoiceClipCacheResult(**stats, max_mb=_prefs(path).voice.clip_cache_mb)  # type: ignore[arg-type]


@dataclass
class VoiceImportResult:
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    written: bool = False
    dry_run: bool = False


class VoiceImportHomeHiroTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "voice_import_homehiro"
    description = (
        "Import HomeHiro's TTS profiles (a copy of homehiro.db) as voice profiles hh-<HomeHiro id>, once. "
        "dry_run shows what it would write"
    )
    params = {
        "db_path": ToolParam(str, "Path to a copy of HomeHiro's homehiro.db"),
        "dry_run": ToolParam(bool, "Only show what would be written", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, db_path: str, dry_run: bool = False, workspace: str | None = None) -> VoiceImportResult:
        from ..services.voice.import_homehiro import read_plan

        _wid, path = _workspace(workspace)
        plan = read_plan(Path(db_path).expanduser())
        if not dry_run and plan.profiles:
            _write_prefs(path, {f"voice.profiles.{pid}": fields for pid, fields in plan.profiles.items()})
            plan.written = True
            log.info(f"✅ HomeHiro voice profiles imported — {len(plan.profiles)} profiles")
        return VoiceImportResult(**plan.to_dict(), dry_run=bool(dry_run))
