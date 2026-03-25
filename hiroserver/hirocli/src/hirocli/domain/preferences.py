"""Workspace preferences — single source of truth for all configurable choices.

preferences.json is the sole authority for which LLMs are available, which is
default for each purpose (chat, STT, TTS), voice settings, audio behavior, and
short-term memory / summarization (``memory``).
No other code path provides a backup answer.  Services call resolve_llm() and
use what they get; if the result is None the service fails clearly.

Storage: ``<workspace>/preferences.json`` — Pydantic model serialised to JSON.
The I/O layer (load_preferences / save_preferences) is the only code that
touches the file.  Swapping to SQLite JSONB later means changing only those two
functions; the model, resolvers, and all consumers stay untouched.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from hiro_commons.constants.storage import PREFERENCES_FILENAME

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM registry
# ---------------------------------------------------------------------------

LLMPurpose = Literal["chat", "stt", "tts"]


class LLMEntry(BaseModel):
    """A registered LLM that the workspace can use."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    provider: str
    model: str
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)
    capabilities: list[str] = Field(default_factory=list)


class LLMPreferences(BaseModel):
    registered: list[LLMEntry] = Field(default_factory=list)
    default_chat: str | None = None
    default_stt: str | None = None
    default_tts: str | None = None


# ---------------------------------------------------------------------------
# Audio / voice
# ---------------------------------------------------------------------------


class VoiceOption(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider: str
    model: str
    voice: str
    instructions: str = ""


class AudioPreferences(BaseModel):
    agent_replies_in_voice: bool = False
    accept_voice_from_user: bool = True
    selected_voice: str | None = None
    voice_options: list[VoiceOption] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Short-term memory (LangGraph + LangMem summarization)
# ---------------------------------------------------------------------------


class MemoryPreferences(BaseModel):
    """Token-bounded conversation context before the chat LLM (see summarizing_agent_graph)."""

    summarization_enabled: bool = True
    max_context_tokens: int = Field(default=4096, ge=512)
    max_tokens_before_summary: int | None = Field(
        default=None,
        description="None = same as max_context_tokens",
    )
    max_summary_tokens: int = Field(default=256, ge=64)
    summarization_llm_id: str | None = Field(
        default=None,
        description="Registered LLM id for summaries; None = use default chat model",
    )


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------


class WorkspacePreferences(BaseModel):
    """Root preferences object persisted as preferences.json."""

    version: int = 1
    llm: LLMPreferences = Field(default_factory=LLMPreferences)
    audio: AudioPreferences = Field(default_factory=AudioPreferences)
    memory: MemoryPreferences = Field(default_factory=MemoryPreferences)


# ---------------------------------------------------------------------------
# I/O — the only code that touches the file
# ---------------------------------------------------------------------------


def preferences_file(workspace_path: Path) -> Path:
    return workspace_path / PREFERENCES_FILENAME


def load_preferences(workspace_path: Path) -> WorkspacePreferences:
    f = preferences_file(workspace_path)
    if f.exists():
        return WorkspacePreferences.model_validate_json(f.read_text(encoding="utf-8"))
    return WorkspacePreferences()


def save_preferences(workspace_path: Path, prefs: WorkspacePreferences) -> None:
    workspace_path.mkdir(parents=True, exist_ok=True)
    preferences_file(workspace_path).write_text(
        prefs.model_dump_json(indent=2), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Resolver — THE single function that answers "which LLM for this purpose?"
#
# All selection logic lives here.  Consuming code MUST NOT add its own
# fallback, env-var lookup, or hardcoded default.
# ---------------------------------------------------------------------------


def resolve_llm(prefs: WorkspacePreferences, purpose: LLMPurpose = "chat") -> LLMEntry | None:
    """Deterministic LLM resolution for a given purpose.

    Resolution order (all within this function, nowhere else):
      1. Explicit default ID for the purpose (default_chat, default_stt, …).
      2. First registered LLM with a matching capability tag.
      3. First registered LLM (if only one, it answers for everything).
      4. None — means "not configured"; caller raises a clear error.
    """
    pool = prefs.llm.registered
    if not pool:
        return None

    # 1. Explicit default
    default_id: str | None = getattr(prefs.llm, f"default_{purpose}", None)
    if default_id:
        for entry in pool:
            if entry.id == default_id:
                return entry

    # 2. First with matching capability
    for entry in pool:
        if purpose in entry.capabilities:
            return entry

    # 3. First registered
    return pool[0]


def resolve_summarization_llm(prefs: WorkspacePreferences) -> LLMEntry | None:
    """LLM used for conversation summarization; falls back to chat when unset or id missing."""
    mem = prefs.memory
    if mem.summarization_llm_id:
        for entry in prefs.llm.registered:
            if entry.id == mem.summarization_llm_id:
                return entry
    return resolve_llm(prefs, "chat")


def resolve_voice(prefs: WorkspacePreferences) -> VoiceOption | None:
    """Resolve the active voice option.

    Same philosophy: selected_voice ID > first option > None.
    """
    options = prefs.audio.voice_options
    if not options:
        return None

    if prefs.audio.selected_voice:
        for opt in options:
            if opt.id == prefs.audio.selected_voice:
                return opt

    return options[0]
