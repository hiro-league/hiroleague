"""Chat-answering behavior (``prefs.chat``). Split out of ``models.py`` for readability."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .defaults import DEFAULT_CHAT_INSTRUCTIONS

# Conversation-history window kept per turn (short-term context for trim_history). Lives under
# ``chat`` (it feeds the chat answer + memory/knowledge retrieval), not under ``memory``.
DEFAULT_MAX_HISTORY_MESSAGES = 6


class ChatPreferences(BaseModel):
    """Chat-answering behavior (the chat model answers; not the Ask knowledge answerer)."""

    # General answering instructions (Markdown), injected into the current user turn. Editable in
    # the Admin → Preferences → Agent tab. Broader than knowledge — may carry any answering guidance.
    instructions: str = Field(default=DEFAULT_CHAT_INSTRUCTIONS, title="Chat instructions")
    # Conversation-history window kept per turn by trim_history (short-term context). Feeds the chat
    # answer + memory/knowledge retrieval — a chat-answering concern, not a long-term memory one.
    max_messages: int = Field(default=DEFAULT_MAX_HISTORY_MESSAGES, ge=1, le=100, title="Max retained messages", description="Conversation history window kept per turn (short-term context for the reply + memory/knowledge retrieval).")
    # When on, chat instructs the model to cite knowledge inline as [n] AND surfaces the source list
    # to the client (citation bridge on graph.reply.completed). Moved here from knowledge.chat.
    cite_sources: bool = Field(default=False, title="Cite knowledge sources in chat replies")
    # Global tools kill-switch for the chat agent. When off, no tools are bound to the chat model on
    # any turn (the chat page's per-message "disable tools" toggle can additionally opt out a single
    # turn). Gated at runtime in call_model; default on.
    tools_enabled: bool = Field(default=True, title="Enable agent tools in chat")
    # Placeholder until a real per-character/per-chat language setting exists; chat retrieval does
    # not constrain answer language today (the persona decides). Kept so it can be threaded later.
    preferred_answering_language: str = "en"
