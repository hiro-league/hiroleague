"""Agent memory settings (``prefs.memory``). Split out of ``models.py`` for readability.

A thin feature layer over the shared Graphiti graph engine (``prefs.graph``): gated by ``enabled``,
with the extraction model / embedder / search coming from the top-level graph preferences.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# DEFAULT_MEMORY_EXTRACTION_INSTRUCTIONS lives in ``defaults`` alongside PROMPT_DEFAULTS (mirroring
# chat.instructions), so the admin prompt-editor "Restore default" restores it — a memory-scoped
# extraction clause with {user}/{character} placeholders filled at ingest with the real speaker
# names. NOT the shared ``graph.custom_extraction_instructions`` (knowledge + eval) nor
# ``chat.instructions`` (answer-time persona guidance, a different pipeline stage).
from .defaults import (
    DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID,
    DEFAULT_MEMORY_EXTRACTION_INSTRUCTIONS,
    DEFAULT_MEMORY_TUNING_PROFILE_ID,
    pref_field,
)
from .models_graph import RetrievalAgentLimits


def default_chat_retrieval_limits() -> RetrievalAgentLimits:
    """Chat retrieval-loop defaults — intentionally leaner than the shared eval defaults
    (fewer agent turns and smaller result counts) so chat recall stays fast and cheap. Kept as a
    chat-only factory so ``graph.eval.retrieval_agent`` keeps the ``RetrievalAgentLimits`` class
    defaults (they no longer share the same numbers)."""
    return RetrievalAgentLimits(
        max_agent_turns=3, limit_default=10, limit_min=5, limit_max=25
    )


class MemorySearchPreferences(BaseModel):
    """Retrieval-time tuning for ``MemoryService.search``."""

    # When false, ``memory_recall`` is skipped — no long-term memory is injected before the reply
    # (independent of extraction). No-op unless ``memory.enabled``.
    enabled: bool = Field(default=True, title="Recall memories before each reply")
    # NOTE: the former ``top_k`` recall-depth knob was removed — chat recall is now the agentic loop,
    # which draws its per-search result count from ``memory.retrieval.limits`` (Num results
    # default/min/max), not a single top-k. ``memory.search.enabled`` is the only search-side knob.


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
        default=3,
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
    chunk_min_tokens: int = pref_field(
        # Advanced: a Graphiti-chunker guard rail, not a day-to-day knob.
        advanced=True,
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
    session_gap_minutes: int = pref_field(
        # Advanced: batching-boundary tuning hidden behind the "show advanced" toggle.
        advanced=True,
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
    idle_flush_hours: int = pref_field(
        # Advanced: background-sweep backstop tuning hidden behind the "show advanced" toggle.
        advanced=True,
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
    instructions: str = pref_field(
        # Advanced: fact-extraction guidance most users leave at the default.
        advanced=True,
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


class MemoryRetrievalRenderPreferences(BaseModel):
    """How recalled memory is rendered into the CHAT persona prompt (memory-eval-vs-chat-parity,
    Phase 3). Chat's own copy of eval's ``RecallRenderOptions`` — which temporal annotations show +
    per-kind caps — so chat drops the flat ``memory_block`` for the rich `format_recall_context`
    layout. Mirrors the eval "Answer context" caps (``graph.eval.max_*``) + temporal toggles
    (``graph.eval.show_*``); the runtime builds a ``RecallRenderOptions`` from these."""

    # Temporal annotations per recalled FACT line. Defaults = a single timestamp per fact (event_time
    # on, the rest off), matching eval.
    show_event_time: bool = Field(default=True, title="Show event_time (valid date)")
    show_expired_at: bool = Field(default=False, title="Show expired_at (invalid date)")
    show_superseded: bool = Field(default=False, title="Show SUPERSEDED flag")
    # Render caps: each kind is score-ranked desc, top-N kept, every element sanitized to one capped
    # line — so a large recalled set doesn't bury the answer-relevant elements or blow the prompt.
    max_elements_per_kind: int = pref_field(advanced=True, default=15, ge=1, le=200, title="Max elements / kind", description="Top-N facts / entities / messages (by retrieval score) kept in the recalled-memory block.")
    max_fact_chars: int = pref_field(advanced=True, default=240, ge=40, le=2000, title="Max fact chars", description="Each recalled fact → one sanitized line capped here.")
    max_episode_chars: int = pref_field(advanced=True, default=300, ge=40, le=2000, title="Max message chars", description="Per-episode/message text cap (one sanitized line).")
    max_summary_chars: int = pref_field(advanced=True, default=400, ge=40, le=4000, title="Max entity summary chars", description="Per-entity summary cap (one sanitized line).")


class MemoryRetrievalPreferences(BaseModel):
    """Chat-side agentic memory-retrieval loop config (memory-eval-vs-chat-parity, Phase 1).

    The prompt LIBRARY is shared with eval (``graph.eval.retrieval_agent_prompts``); this section
    holds chat's own SELECTION (``active_prompt_id``), caps, and model, so chat tunes independently of
    eval (the deferred ``memory.retrieval.*`` split, brought forward). Consumed when the loop is wired
    into the recall node (Phase 2) — fields only today."""

    # Selects a profile from the SHARED library (graph.eval.retrieval_agent_prompts); defaults to the
    # locked ``chat`` profile. The library dict is owned by the Graph-Engine card; the Agent-memory
    # card only owns this pointer (via the active-id-only dropdown widget).
    active_prompt_id: str = Field(
        default=DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID,
        title="Active prompt profile",
        description="Which shared retrieval-agent prompt profile the CHAT recall loop uses.",
    )
    # Chat's OWN loop caps — leaner than eval (max_agent_turns=3, num-results 5/10/25). Split from
    # eval (its own factory) so chat is tuned independently; eval keeps the class defaults.
    limits: RetrievalAgentLimits = Field(default_factory=default_chat_retrieval_limits)
    model: str | None = pref_field(
        model_kind="chat",
        default=None,
        title="Retrieval agent model",
        description=(
            "Model the CHAT agentic retrieval loop uses to plan searches and call the search_memory "
            "tool. Null falls back to the default chat model."
        ),
    )
    tuning_profile: str = pref_field(
        tuning_profile_ref=True,
        # Defaults to the "Retrieval Agent Profile" (deterministic, roomy budget, light reasoning).
        default=DEFAULT_MEMORY_TUNING_PROFILE_ID,
        title="Retrieval agent profile",
        description="Tuning profile (temperature / max-tokens / thinking) for the chat retrieval-agent model.",
    )
    render: MemoryRetrievalRenderPreferences = Field(
        default_factory=MemoryRetrievalRenderPreferences
    )


class MemoryPreferences(BaseModel):
    """Agent memory settings — a thin feature layer over the shared Graphiti graph engine.

    Gated purely by ``enabled``; the engine (extraction model, embedder, search) comes from
    the top-level ``graph`` preferences, and ``create_memory_service`` degrades to ``None``
    when that engine can't be built. The mem0-legacy model / embedder / reranker fields are
    gone (mem0 → Graphiti, Phase 5)."""

    enabled: bool = Field(default=True, title="Enable agent memory")
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
    retrieval: MemoryRetrievalPreferences = Field(default_factory=MemoryRetrievalPreferences)
