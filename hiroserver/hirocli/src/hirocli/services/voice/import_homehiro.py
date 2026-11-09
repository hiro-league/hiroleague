"""Importing HomeHiro's TTS profiles into the core's voice profiles, once (Phase 7b).

Reads a copy of HomeHiro's ``homehiro.db`` (read-only): ``ttsprofile`` (id, name, provider, model,
voice_id, voice_label, style, options). Each becomes voice profile ``hh-<HomeHiro id>`` (HomeHiro's
alerts and Speak nodes keep their old profile id and send it as ``hh-<id>``), named as it was:

- provider ``gemini`` → ``google``, ``openai`` stays; the model becomes the catalog id
  (``google:gemini-3.8-flash-tts``); a pinned OpenAI model the catalog doesn't list
  (``gpt-4o-mini-tts-2025-12-15``) becomes ``openai:gpt-4o-mini-tts``, with a note;
- the voice, its label, the style and the speed (``options.speed``, OpenAI only) as they are.

A profile whose model can't be mapped is left out with a note. A dry run writes nothing. Profiles with an
id already in preferences are replaced; everything else stays. Designed voices need nothing: they live in
the Google account, which the core reaches with the same key.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ...domain.preferences import VoiceProfile

PROVIDERS = {"gemini": "google", "openai": "openai"}
PINNED = {"gpt-4o-mini-tts-2025-12-15": "gpt-4o-mini-tts"}


class VoiceImportError(ValueError):
    """The file isn't a HomeHiro database with TTS profiles."""


@dataclass
class VoiceImportPlan:
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)  # hh-<id> → voice profile fields
    notes: list[str] = field(default_factory=list)
    written: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_plan(db_file: Path) -> VoiceImportPlan:
    rows = _read(db_file)
    plan = VoiceImportPlan()
    for r in rows:
        name = str(r.get("name") or r["id"])
        provider = PROVIDERS.get(str(r.get("provider") or ""))
        if provider is None:
            plan.notes.append(f"{name}: left out (provider {r.get('provider')!r} isn't one the core speaks with)")
            continue
        model = str(r.get("model") or "")
        if model in PINNED:
            plan.notes.append(f"{name}: {model} is now {PINNED[model]} (the catalog lists the latest only)")
            model = PINNED[model]
        try:
            options = json.loads(r.get("options") or "{}") if isinstance(r.get("options"), str) else (r.get("options") or {})
            profile = VoiceProfile(
                label=name,
                model=f"{provider}:{model}",
                voice=str(r.get("voice_id") or ""),
                voice_label=str(r.get("voice_label") or ""),
                style=str(r.get("style") or ""),
                speed=float(options.get("speed", 1.0)) if provider == "openai" else 1.0,
            )
        except (ValidationError, ValueError, TypeError, AttributeError) as exc:
            plan.notes.append(f"{name}: left out ({str(exc).splitlines()[0]})")
            continue
        plan.profiles[f"hh-{r['id']}"] = profile.model_dump()
    return plan


def _read(db_file: Path) -> list[dict[str, Any]]:
    if not db_file.is_file():
        raise VoiceImportError(f"No such file: {db_file}")
    try:
        conn = sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise VoiceImportError(f"Can't open {db_file}: {exc}") from exc
    try:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "ttsprofile" not in tables:
            raise VoiceImportError(f"{db_file} has no TTS profiles (ttsprofile): is it HomeHiro's homehiro.db?")
        return [dict(r) for r in conn.execute("SELECT * FROM ttsprofile ORDER BY name")]
    except sqlite3.Error as exc:
        raise VoiceImportError(f"Can't read {db_file}: {exc}") from exc
    finally:
        conn.close()
