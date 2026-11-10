"""One-time conversion of ``preferences.json`` v3 → v4 (Phase 7b step 5: AI profiles for Hiro's jobs).

The owner asked for this one conversion (the no-backward-compatibility rule otherwise applies): v3
picked "a model + a tuning profile" per job and model lists per character; v4 points each job at one
AI profile, characters at ordered lists of AI and voice profiles, and Hiro's spoken replies at a voice
profile (``voice.hiro_profile``). Runs from ``load_preferences`` on the RAW JSON, before validation,
when ``version < 4``; a v4 file is never touched (idempotent).

What it does:

1. Copies ``preferences.json`` to ``preferences.v3.json`` (only when that copy doesn't exist yet).
2. Each job (``jobs.JOB_PRESETS``): the model the old resolver would have used (the job's own model
   field, else the old fallback chain) and the tuning of the old referenced tuning profile (the raw
   ``tuning_profiles`` entry, else the old preset's values) become AI profile ``hiro-<job>`` with
   ``preset=<job>``, and the job's field points at it. No model anywhere → no profile, field null.
   Reading pictures: ``IMAGE_VISION_MODEL`` from the environment when set, else ``openai:gpt-4o-mini``
   when an OpenAI key is configured, else null.
3. Characters: each ``characters/<id>/character.json`` still holding the old keys is copied to
   ``character.v3.json`` once; each ``llm_models`` entry becomes AI profile ``<id>-<n>``, each
   ``voice_models`` entry voice profile ``<id>-voice-<n>``; the new ``ai_profiles`` /
   ``voice_profiles`` lists replace the old keys.
4. Hiro's voice: ``voice.hiro_profile`` = voice profile ``hiro-voice`` made from ``llm.default_tts``
   and the default character's voice for that provider + its TTS instructions (as the style).
5. A model the catalog doesn't know (the profile would be refused) is skipped with a WARNING naming
   the job and model — the load never fails because of it.

The caller validates the result, saves it as version 4 and logs one summary line.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.constants.storage import CHARACTERS_DIR, DEFAULT_CHARACTER_ID, PREFERENCES_FILENAME

from .jobs import JOB_PRESETS, job_preset, unique_profile_id

logger = logging.getLogger(__name__)

PREFERENCES_V3_BACKUP = "preferences.v3.json"
CHARACTER_V3_BACKUP = "character.v3.json"
CHARACTER_JSON = "character.json"
V4 = 4

# Old character keys replaced by ai_profiles / voice_profiles.
OLD_CHARACTER_KEYS = ("llm_models", "tuning_profile", "voice_models", "tts_instructions", "tts_voice_by_provider")
# A provider's voice when the old character named none for it (Gemini studio voice / OpenAI voice).
DEFAULT_VOICE = {"google": "kore", "openai": "sage"}
# Vision's old built-in default (services/vision_service.py, overridable by IMAGE_VISION_MODEL).

# The old built-in tuning presets, by their old id → the job whose preset holds the same values.
OLD_TUNING_PRESET_JOB = {
    "balanced_chat": "chat",
    "memory_extraction": "memory",
    "knowledge_answering": "knowledge",
    "knowledge_rewrite": "rewrite",
    "graphiti_extraction": "graph_extraction",
    "graphiti_small": "graph_small",
}

# Per job: (old model fields in fallback order, the old field naming its tuning profile, its default).
# Mirrors the old resolvers exactly (resolvers.py before v4).
_OLD_CHAIN = ("knowledge.answering.model", "llm.default_chat")
OLD_JOB_SOURCES: dict[str, tuple[tuple[str, ...], str | None, str]] = {
    "chat": (("llm.default_chat",), "llm.default_tuning_profile", "balanced_chat"),
    "memory": (("memory.retrieval.model", "llm.default_chat"), "memory.retrieval.tuning_profile", "memory_extraction"),
    "knowledge": (_OLD_CHAIN, "knowledge.default_tuning_profile", "knowledge_answering"),
    "rewrite": (_OLD_CHAIN, None, "knowledge_rewrite"),
    "graph_extraction": (
        ("graph.extraction_model", *_OLD_CHAIN), "graph.extraction_tuning_profile", "graphiti_extraction"
    ),
    "graph_small": (
        ("graph.small_model", "graph.extraction_model", *_OLD_CHAIN), "graph.small_tuning_profile", "graphiti_small"
    ),
    "eval_answer": (("graph.eval.answer_model", *_OLD_CHAIN), "graph.eval.answer_tuning_profile", "knowledge_answering"),
    "eval_judge": (("graph.eval.judge_model", *_OLD_CHAIN), "graph.eval.judge_tuning_profile", "knowledge_answering"),
    "eval_retrieval": (
        ("graph.eval.retrieval_model", "graph.eval.answer_model", *_OLD_CHAIN),
        "graph.eval.retrieval_tuning_profile",
        "knowledge_answering",
    ),
}

# Old leaves dropped from the raw JSON (pydantic would ignore them, but the saved v4 file stays clean).
OLD_PREFERENCE_PATHS = (
    "llm.default_chat",
    "llm.default_tts",
    "llm.default_tuning_profile",
    "memory.default_tuning_profile",
    "memory.retrieval.model",
    "memory.retrieval.tuning_profile",
    "knowledge.answering.model",
    "knowledge.default_tuning_profile",
    "graph.extraction_model",
    "graph.extraction_tuning_profile",
    "graph.small_model",
    "graph.small_tuning_profile",
    "graph.eval.answer_model",
    "graph.eval.answer_tuning_profile",
    "graph.eval.judge_model",
    "graph.eval.judge_tuning_profile",
    "graph.eval.retrieval_model",
    "graph.eval.retrieval_tuning_profile",
    "tuning_profiles",
)


@dataclass
class ConversionSummary:
    """What the conversion did (one INFO line from the caller)."""

    jobs: dict[str, str] = field(default_factory=dict)  # job → profile id
    jobs_off: list[str] = field(default_factory=list)  # no model anywhere
    skipped: list[str] = field(default_factory=list)  # "<what>: <model> (<why>)"
    characters: list[str] = field(default_factory=list)
    ai_profiles: int = 0
    voice_profiles: int = 0
    hiro_voice: str | None = None
    backup: str | None = None
    # Character files to write once the converted preferences validated: path → new JSON.
    pending_characters: dict[Path, dict[str, Any]] = field(default_factory=dict)

    def line(self) -> str:
        parts = [f"jobs → {', '.join(f'{j}={p}' for j, p in self.jobs.items()) or 'none'}"]
        if self.jobs_off:
            parts.append(f"no model: {', '.join(self.jobs_off)}")
        if self.characters:
            parts.append(f"characters: {', '.join(self.characters)}")
        parts.append(f"Hiro's voice: {self.hiro_voice or 'none'}")
        if self.skipped:
            parts.append(f"skipped: {'; '.join(self.skipped)}")
        return " · ".join(parts)


def needs_conversion(data: Any) -> bool:
    """True for a raw preferences dict older than v4."""
    if not isinstance(data, dict):
        return False
    try:
        return int(data.get("version") or 0) < V4
    except (TypeError, ValueError):
        return True


def convert_preferences_v3_to_v4(workspace_path: Path, data: dict[str, Any]) -> tuple[dict[str, Any], ConversionSummary]:
    """Convert the raw v3 dict (a copy is returned; ``data`` is not changed). See the module notes.

    Character files are NOT written here: the caller writes ``summary.pending_characters`` with
    :func:`write_converted_characters` after the converted preferences validated.
    """
    summary = ConversionSummary()
    summary.backup = _backup_preferences(workspace_path)
    out: dict[str, Any] = json.loads(json.dumps(data))  # deep copy of plain JSON
    raw_tuning = out.get("tuning_profiles") if isinstance(out.get("tuning_profiles"), dict) else {}
    ai = out.setdefault("ai", {})
    if not isinstance(ai, dict):
        ai = out["ai"] = {}
    profiles: dict[str, Any] = ai.setdefault("profiles", {})
    voice = out.setdefault("voice", {})
    if not isinstance(voice, dict):
        voice = out["voice"] = {}
    voice_profiles: dict[str, Any] = voice.setdefault("profiles", {})

    for job in JOB_PRESETS:
        _convert_job(workspace_path, out, job, raw_tuning, profiles, summary)

    default_char = _default_character_raw(workspace_path)
    _convert_hiro_voice(out, default_char, voice, voice_profiles, summary)
    _convert_characters(workspace_path, raw_tuning, profiles, voice_profiles, summary)

    for path in OLD_PREFERENCE_PATHS:
        _pop_path(out, path)
    out["version"] = V4
    return out, summary


def write_converted_characters(summary: ConversionSummary) -> None:
    """Write the converted character files (backups were made during the conversion)."""
    for path, payload in summary.pending_characters.items():
        try:
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.error(
                "❌ Character not converted — %s · writing character.json failed",
                path.parent.name,
                extra={"error": str(exc), "path": str(path)},
            )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def _convert_job(
    workspace_path: Path,
    out: dict[str, Any],
    job: str,
    raw_tuning: dict[str, Any],
    profiles: dict[str, Any],
    summary: ConversionSummary,
) -> None:
    preset = job_preset(job)
    if job == "vision":
        model = _old_vision_model(workspace_path, out, profiles)
        tuning = _preset_tuning(job)
    else:
        model_paths, tuning_path, tuning_default = OLD_JOB_SOURCES[job]
        model = _first_set(out, model_paths)
        tuning_id = (str(_get_path(out, tuning_path) or "").strip() if tuning_path else "") or tuning_default
        tuning = _old_tuning(raw_tuning, tuning_id, fallback_job=job)
    if not model:
        summary.jobs_off.append(job)
        _set_path(out, preset.path, None)
        return
    # A chat model the catalog no longer lists (pruned by a models refresh) would leave the job off — Hiro
    # silent. Use its provider's recommended chat model instead, as the voice conversion does (logged).
    model = _chat_model(model, what=f"job {job}")
    payload = {"label": preset.label, "model": model, "preset": job, **tuning}
    if not _valid_ai_profile(payload, what=f"job {job}", summary=summary):
        _set_path(out, preset.path, None)
        return
    pid = unique_profile_id(profiles, preset.profile_id)
    profiles[pid] = payload
    _set_path(out, preset.path, pid)
    summary.jobs[job] = pid
    summary.ai_profiles += 1


def _old_vision_model(workspace_path: Path, out: dict[str, Any], profiles: dict[str, Any]) -> str | None:
    """IMAGE_VISION_MODEL when it was set; else the converted chat profile's model. (Not the old default
    openai:gpt-4o-mini: the catalog dropped it, and its replacement would be OpenAI's flagship — far too
    costly for describing a photo. Hiro's chat model reads pictures and is the one already paid for.)"""
    env = (os.environ.get("IMAGE_VISION_MODEL") or "").strip()
    if env:
        return env
    chat = profiles.get(str(_get_path(out, job_preset("chat").path) or ""))
    if isinstance(chat, dict) and chat.get("model"):
        return str(chat["model"])
    logger.info(
        "Reading pictures left off — no IMAGE_VISION_MODEL and no chat profile · preferences v4 conversion",
        extra={"workspace_path": str(workspace_path)},
    )
    return None




def _preset_tuning(job: str) -> dict[str, Any]:
    preset = job_preset(job)
    return {"temperature": preset.temperature, "max_tokens": preset.max_tokens, "thinking": preset.thinking}


def _old_tuning(raw_tuning: dict[str, Any], tuning_id: str, *, fallback_job: str) -> dict[str, Any]:
    """The old tuning profile's values (raw entry, else the old preset by id, else the job's preset)."""
    entry = raw_tuning.get(tuning_id) if isinstance(raw_tuning, dict) else None
    if isinstance(entry, dict):
        base = _preset_tuning(OLD_TUNING_PRESET_JOB.get(tuning_id, fallback_job))
        tuning = {
            "temperature": entry.get("temperature", base["temperature"]),
            "max_tokens": entry.get("max_tokens", base["max_tokens"]),
            "thinking": entry.get("thinking", base["thinking"]),
        }
        if entry.get("num_ctx"):
            # AiProfile's floor is 256 (ModelTuning allowed 1); a tiny value would be refused.
            tuning["num_ctx"] = max(256, int(entry["num_ctx"]))
        return tuning
    return _preset_tuning(OLD_TUNING_PRESET_JOB.get(tuning_id, fallback_job))


def _chat_model(model: str, *, what: str) -> str:
    """``model`` when the catalog lists it as a chat model (or it's a local / plan model, checked later); else its
    provider's recommended chat model, logged. Unknown providers come back unchanged (then skipped as invalid)."""
    from ..model_catalog import get_model_catalog

    provider = model.partition(":")[0]
    cat = get_model_catalog()
    prov = cat.get_provider(provider)
    if prov is None or prov.hosting == "local":
        return model
    spec = cat.get_model(model)
    if spec is not None and spec.supports_kind("chat"):
        return model
    recommended = cat.suggested_defaults(provider).get("chat")
    if not recommended:
        return model
    logger.warning(
        "⚠️ Chat model replaced — %s · %s isn't in the catalog any more, using %s · preferences v4 conversion",
        what,
        model,
        recommended,
    )
    return recommended


def _valid_ai_profile(payload: dict[str, Any], *, what: str, summary: ConversionSummary) -> bool:
    from pydantic import ValidationError

    from .models_ai import AiProfile

    try:
        AiProfile.model_validate(payload)
    except ValidationError as exc:
        reason = exc.errors()[0].get("msg", str(exc)) if exc.errors() else str(exc)
        logger.warning(
            "⚠️ AI profile not made — %s · model %s · preferences v4 conversion",
            what,
            payload.get("model"),
            extra={"error": reason},
        )
        summary.skipped.append(f"{what}: {payload.get('model')} ({reason})")
        return False
    return True


# ---------------------------------------------------------------------------
# Voices
# ---------------------------------------------------------------------------


def _speech_model(model: str, *, what: str) -> str | None:
    """A catalog speech model for ``model``: itself, or its provider's recommended one (logged)."""
    from ..model_catalog import get_model_catalog
    from .models_voice import VOICE_PROVIDERS

    provider = model.partition(":")[0]
    if provider not in VOICE_PROVIDERS:
        return None
    cat = get_model_catalog()
    spec = cat.get_model(model)
    if spec is not None and spec.supports_kind("tts"):
        return model
    recommended = cat.suggested_defaults(provider).get("tts")
    if recommended:
        logger.info(
            "Speech model replaced — %s · %s isn't a catalog speech model, using %s · preferences v4 conversion",
            what,
            model,
            recommended,
        )
    return recommended


def _voice_payload(
    model: str, *, label: str, voice_by_provider: dict[str, Any], style: str, what: str, summary: ConversionSummary
) -> dict[str, Any] | None:
    from pydantic import ValidationError

    from .models_voice import VoiceProfile

    speech = _speech_model(model, what=what)
    if speech is None:
        logger.warning("⚠️ Voice profile not made — %s · model %s · preferences v4 conversion", what, model)
        summary.skipped.append(f"{what}: {model} (not a speech model of google/openai)")
        return None
    provider = speech.partition(":")[0]
    voice = str(voice_by_provider.get(provider) or "").strip() or DEFAULT_VOICE[provider]
    if provider == "google":
        voice = voice.lower()  # the old Gemini voices were named ("Kore"); the Voices API ids are lowercase
    elif voice not in _openai_voices():
        voice = DEFAULT_VOICE["openai"]
    payload = {"label": label, "model": speech, "voice": voice, "style": str(style or "")[:2000]}
    try:
        VoiceProfile.model_validate(payload)
    except ValidationError as exc:
        reason = exc.errors()[0].get("msg", str(exc)) if exc.errors() else str(exc)
        logger.warning(
            "⚠️ Voice profile not made — %s · model %s · preferences v4 conversion", what, speech, extra={"error": reason}
        )
        summary.skipped.append(f"{what}: {speech} ({reason})")
        return None
    return payload


def _openai_voices() -> list[str]:
    from ..model_catalog import get_model_catalog

    provider = get_model_catalog().get_provider("openai")
    return [v.id for v in (provider.tts_voices if provider else [])]


def _convert_hiro_voice(
    out: dict[str, Any],
    default_char: dict[str, Any],
    voice: dict[str, Any],
    voice_profiles: dict[str, Any],
    summary: ConversionSummary,
) -> None:
    old_tts = str(_get_path(out, "llm.default_tts") or "").strip()
    voice["hiro_profile"] = None
    if not old_tts:
        return
    voice_map = default_char.get("tts_voice_by_provider") if isinstance(default_char.get("tts_voice_by_provider"), dict) else {}
    payload = _voice_payload(
        old_tts,
        label="Hiro's voice",
        voice_by_provider=voice_map,
        style=str(default_char.get("tts_instructions") or ""),
        what="Hiro's voice",
        summary=summary,
    )
    if payload is None:
        return
    pid = unique_profile_id(voice_profiles, "hiro-voice")
    voice_profiles[pid] = payload
    voice["hiro_profile"] = pid
    summary.hiro_voice = pid
    summary.voice_profiles += 1


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------


def _default_character_id(workspace_path: Path) -> str:
    """The default character's id from workspace.db, read-only (no seeding while preferences load)."""
    try:
        from ..db import db_path

        path = db_path(workspace_path)
        if not path.is_file():
            return DEFAULT_CHARACTER_ID
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute("SELECT id FROM characters WHERE is_default = 1 LIMIT 1").fetchone()
        return str(row[0]) if row and row[0] else DEFAULT_CHARACTER_ID
    except sqlite3.Error as exc:
        logger.warning("⚠️ Default character unknown — using %s · preferences v4 conversion", DEFAULT_CHARACTER_ID,
                       extra={"error": str(exc)})
        return DEFAULT_CHARACTER_ID


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("⚠️ Character file unreadable — %s · preferences v4 conversion", path.parent.name,
                       extra={"error": str(exc)})
        return None
    return data if isinstance(data, dict) else None


def _default_character_raw(workspace_path: Path) -> dict[str, Any]:
    cid = _default_character_id(workspace_path)
    path = workspace_path / CHARACTERS_DIR / cid / CHARACTER_JSON
    return (_read_json(path) or {}) if path.is_file() else {}


def _convert_characters(
    workspace_path: Path,
    raw_tuning: dict[str, Any],
    profiles: dict[str, Any],
    voice_profiles: dict[str, Any],
    summary: ConversionSummary,
) -> None:
    root = workspace_path / CHARACTERS_DIR
    if not root.is_dir():
        return
    for path in sorted(root.glob(f"*/{CHARACTER_JSON}")):
        raw = _read_json(path)
        if raw is None or not any(k in raw for k in OLD_CHARACTER_KEYS):
            continue
        backup = path.with_name(CHARACTER_V3_BACKUP)
        if not backup.exists():
            try:
                shutil.copy2(path, backup)
            except OSError as exc:
                logger.error("❌ Character not converted — %s · backup failed", path.parent.name,
                             extra={"error": str(exc)})
                continue
        cid = str(raw.get("id") or path.parent.name)
        name = str(raw.get("name") or cid)
        ai_ids = _character_ai_profiles(cid, name, raw, raw_tuning, profiles, summary)
        voice_ids = _character_voice_profiles(cid, name, raw, voice_profiles, summary)
        new_raw = {k: v for k, v in raw.items() if k not in OLD_CHARACTER_KEYS}
        new_raw["ai_profiles"] = ai_ids
        new_raw["voice_profiles"] = voice_ids
        summary.pending_characters[path] = new_raw
        summary.characters.append(f"{cid} ({len(ai_ids)} AI, {len(voice_ids)} voice)")


def _character_ai_profiles(
    cid: str,
    name: str,
    raw: dict[str, Any],
    raw_tuning: dict[str, Any],
    profiles: dict[str, Any],
    summary: ConversionSummary,
) -> list[str]:
    tuning_id = str(raw.get("tuning_profile") or "").strip()
    tuning = _old_tuning(raw_tuning, tuning_id, fallback_job="chat") if tuning_id else _preset_tuning("chat")
    ids: list[str] = []
    models = [str(m).strip() for m in (raw.get("llm_models") or []) if str(m).strip()]
    for n, model in enumerate(dict.fromkeys(models), start=1):
        payload = {"label": f"{name}: {model}"[:80], "model": model, **tuning}
        if not _valid_ai_profile(payload, what=f"character {cid}", summary=summary):
            continue
        pid = unique_profile_id(profiles, f"{cid}-{n}")
        profiles[pid] = payload
        ids.append(pid)
        summary.ai_profiles += 1
    return ids


def _character_voice_profiles(
    cid: str,
    name: str,
    raw: dict[str, Any],
    voice_profiles: dict[str, Any],
    summary: ConversionSummary,
) -> list[str]:
    voice_map = raw.get("tts_voice_by_provider") if isinstance(raw.get("tts_voice_by_provider"), dict) else {}
    ids: list[str] = []
    models = [str(m).strip() for m in (raw.get("voice_models") or []) if str(m).strip()]
    for n, model in enumerate(dict.fromkeys(models), start=1):
        payload = _voice_payload(
            model,
            label=f"{name}'s voice {n}"[:80],
            voice_by_provider=voice_map,
            style=str(raw.get("tts_instructions") or ""),
            what=f"character {cid}",
            summary=summary,
        )
        if payload is None:
            continue
        pid = unique_profile_id(voice_profiles, f"{cid}-voice-{n}")
        voice_profiles[pid] = payload
        ids.append(pid)
        summary.voice_profiles += 1
    return ids


# ---------------------------------------------------------------------------
# Files and paths
# ---------------------------------------------------------------------------


def _backup_preferences(workspace_path: Path) -> str | None:
    src = workspace_path / PREFERENCES_FILENAME
    dest = workspace_path / PREFERENCES_V3_BACKUP
    if dest.exists() or not src.is_file():
        return str(dest) if dest.exists() else None
    try:
        shutil.copy2(src, dest)
    except OSError as exc:
        # The conversion still runs (the old file is about to be replaced): say so loudly.
        logger.error("❌ preferences.v3.json backup failed — workspace · preferences v4 conversion",
                     extra={"error": str(exc), "workspace_path": str(workspace_path)})
        return None
    return str(dest)


def _get_path(data: dict[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _first_set(data: dict[str, Any], paths: tuple[str, ...]) -> str | None:
    for path in paths:
        value = str(_get_path(data, path) or "").strip()
        if value:
            return value
    return None


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = node[part] = {}
        node = child
    node[parts[-1]] = value


def _pop_path(data: dict[str, Any], path: str) -> None:
    parts = path.split(".")
    node: Any = data
    for part in parts[:-1]:
        node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return
    node.pop(parts[-1], None)


__all__ = [
    "CHARACTER_V3_BACKUP",
    "ConversionSummary",
    "PREFERENCES_V3_BACKUP",
    "convert_preferences_v3_to_v4",
    "needs_conversion",
    "write_converted_characters",
]
