"""Agent memory settings (``prefs.memory``). Split out of ``models.py`` for readability.

A thin feature layer over the shared Graphiti graph engine (``prefs.graph``): gated by ``enabled``,
with the extraction model / embedder / search coming from the top-level graph preferences.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .defaults import DEFAULT_MEMORY_TUNING_PROFILE_ID, pref_field

DEFAULT_MEMORY_SEARCH_TOP_K = 8

# Default extraction clause the CHAT facade appends when ingesting windowed two-speaker episodes:
# attribute facts to the human user only; the assistant/character lines are context (D2 anti-echo).
# The ``{user}`` / ``{character}`` placeholders are filled at ingest with the ACTUAL speaker names
# (the body uses bare names for A1 anchoring, so the role→name mapping must be stated explicitly or
# the extractor has to guess which speaker is the human). Editable per workspace via
# ``memory.extraction.instructions``. Memory-scoped on purpose — it must NOT ride
# ``graph.custom_extraction_instructions`` (shared with knowledge + eval) nor ``chat.instructions``
# (answer-time persona guidance, a different pipeline stage).
DEFAULT_MEMORY_EXTRACTION_INSTRUCTIONS = (
    'This text is a chat transcript. In it, "{user}" is the human user and "{character}" is the AI '
    "assistant/character; each line is prefixed with its speaker and timestamp. Extract facts ONLY "
    "about {user}, and only as {user} stated or explicitly confirmed them. Treat {character}'s lines "
    "purely as context for resolving what {user} refers to — never record a fact asserted by "
    "{character} that {user} did not state or confirm."
)


class MemorySearchPreferences(BaseModel):
    """Retrieval-time tuning for ``MemoryService.search``."""

    # When false, ``memory_search`` is skipped — no long-term memory is injected before the reply
    # (independent of extraction). No-op unless ``memory.enabled``.
    enabled: bool = Field(default=True, title="Recall memories before each reply")
    top_k: int = Field(
        default=DEFAULT_MEMORY_SEARCH_TOP_K, ge=1, le=100, title="Memories to recall (top K)"
    )


class MemoryExtractionPreferences(BaseModel):
    """Whether — and how — the agent stores new long-term memories after a reply (memory_out)."""

    # When false, ``_store_turn_memory`` is skipped — memory becomes read-only (it stops growing)
    # while search may still inject existing memories. No-op unless ``memory.enabled``.
    enabled: bool = Field(default=True, title="Remember new facts after each reply")

    # Windowed batch ingestion (docs/memory-eval-vs-chat-parity.md → "Ingestion — implementation
    # design"). Chat accumulates whole exchanges (user turn + agent reply) and ingests them as ONE
    # two-speaker episode instead of one user turn per episode, so the extractor gets both sides as
    # coreference context. The batching controller reads these fresh every turn, so changing them
    # mid-conversation is safe — the ingest watermark stores a position, not N. (P1: fields only;
    # the controller that consumes them lands in P2.)
    window_turns: int = Field(
        default=4,
        ge=1,
        le=50,
        title="Turns per memory batch",
        description=(
            "Conversation turns (user+agent exchanges) accumulated into one memory episode before "
            "extraction. 1 = ingest every turn; higher batches more turns into a richer episode."
        ),
    )
    # Guard so a batched episode never trips Graphiti's internal chunker (episode == chunk ==
    # point_id must hold). Mirrors graphiti_core CHUNK_MIN_TOKENS (default 1000); an oversized
    # window sheds turns to fit, a single oversized turn is trimmed. Keep at or below Graphiti's.
    chunk_min_tokens: int = Field(
        default=1000,
        ge=100,
        le=8000,
        title="Max tokens per memory episode",
        description=(
            "Token budget for a batched memory episode. A window over this sheds turns to fit "
            "(a lone oversized turn is trimmed). Keep at/below Graphiti's chunk threshold so an "
            "episode is never re-split."
        ),
    )
    # Reactive session boundary: if the next message arrives more than this after the last pending
    # turn, the pending turns are flushed as a finished session and a new batch starts. Keeps a
    # window's turns temporally tight so its single reference_time stays representative.
    session_gap_minutes: int = Field(
        default=120,
        ge=1,
        le=10080,
        title="New-session gap (minutes)",
        description=(
            "If the next message arrives more than this many minutes after the previous one, the "
            "pending turns are ingested as a finished session and a new batch starts."
        ),
    )
    # Backstop: a background sweep flushes a conversation's pending (un-batched) turns after this
    # long idle, so an abandoned conversation's memories still land even if the user never returns.
    idle_flush_hours: int = Field(
        default=12,
        ge=1,
        le=168,
        title="Idle flush (hours)",
        description=(
            "A background sweep ingests a conversation's pending turns after this many hours of "
            "inactivity, so an abandoned conversation's memories still land."
        ),
    )
    # Extraction-time guidance appended to the graph extractor for chat memory only (NOT knowledge
    # documents or eval, and NOT the answer-time chat instructions). Governs WHICH facts enter the
    # graph from a two-speaker window — by default, only the user's.
    instructions: str = Field(
        default=DEFAULT_MEMORY_EXTRACTION_INSTRUCTIONS,
        max_length=4000,
        title="Memory extraction instructions",
        description=(
            "Guidance appended to the graph fact-extractor when ingesting chat memory (a two-speaker "
            "window). Default: attribute facts to the user only, treating the assistant's lines as "
            "context. Use {user} / {character} placeholders — they are filled with the actual "
            "speaker names at ingest. Applies to conversation memory only — not knowledge or eval."
        ),
    )


class MemoryPreferences(BaseModel):
    """Agent memory settings — a thin feature layer over the shared Graphiti graph engine.

    Gated purely by ``enabled``; the engine (extraction model, embedder, search) comes from
    the top-level ``graph`` preferences, and ``create_memory_service`` degrades to ``None``
    when that engine can't be built. The mem0-legacy model / embedder / reranker fields are
    gone (mem0 → Graphiti, Phase 5)."""

    enabled: bool = Field(default=False, title="Enable agent memory")
    default_tuning_profile: str = pref_field(
        tuning_profile_ref=True, default=DEFAULT_MEMORY_TUNING_PROFILE_ID
    )
    # A1 fix: the human's name, used as the Graphiti *speaker label* when ingesting the user's
    # turns. Graphiti extracts the speaker (the token before the ":") as the anchor entity, so a
    # real name produces a clean `Misho` Person hub instead of a generic `User` node, and every
    # fact the user states attaches to it. Empty ⇒ falls back to "User" (prior behavior).
    # IMPORTANT: keep this STABLE. Graphiti never auto-renames nodes, so changing it mid-history
    # forks a SECOND hub and fragments the user's memory — set it once, early.
    user_name: str = Field(default="", max_length=120, title="Your name")
    search: MemorySearchPreferences = Field(default_factory=MemorySearchPreferences)
    extraction: MemoryExtractionPreferences = Field(default_factory=MemoryExtractionPreferences)
