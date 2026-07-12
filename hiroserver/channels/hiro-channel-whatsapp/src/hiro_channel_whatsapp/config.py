"""WhatsApp channel configuration schema (design §5.1).

Declares the channel's config keys as a pydantic model. ``model_json_schema()`` is
shipped to the server at registration (``ChannelInfo.config_schema``) so the server
can validate config writes and the admin UI can render the settings form
generically — the server never imports this module (plugins run in isolated envs).

This model is the single source of truth for *what keys exist*; the running plugin
still reads the pushed config dict directly (see ``plugin.on_configure``), so a
value stored before a schema field existed is tolerated.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WhatsAppChannelConfig(BaseModel):
    """Editable configuration for the WhatsApp channel."""

    # extra="forbid" ⇒ the JSON Schema sets additionalProperties:false, so the
    # server rejects a typo'd/unknown config key at write time.
    model_config = ConfigDict(extra="forbid")

    owner_number: str | None = Field(
        default=None,
        title="Owner number",
        description=(
            "Your own WhatsApp number (digits only). Messages from it route to the "
            "default conversation and it is always allow-listed."
        ),
    )
    allowed_senders: list[str] = Field(
        default_factory=list,
        title="Allowed senders",
        description=(
            "Phone numbers permitted to reach the agent. Empty ⇒ only the owner "
            "number is allowed (the allow-list is closed by default)."
        ),
    )
    send_read_receipts: bool = Field(
        default=True,
        title="Send read receipts",
        description="Show blue ticks when the assistant reads an incoming message.",
    )
    audio_in: bool = Field(
        default=True,
        title="Accept voice notes",
        description="Transcribe inbound WhatsApp voice notes and pass them to the agent.",
    )
    audio_out: bool = Field(
        default=True,
        title="Reply with voice notes",
        description="When the character speaks (TTS ran), also send a WhatsApp voice note.",
    )
    default_character_id: str | None = Field(
        default=None,
        title="Default character",
        description="Character for new conversations (default: the workspace default).",
    )
    default_channel: str | None = Field(
        default=None,
        title="Default conversation",
        description="Conversation the owner's messages route to (default: General).",
    )
    session_db_path: str | None = Field(
        default=None,
        title="Session database path",
        description=(
            "Where the WhatsApp link session is stored. Default: under the workspace "
            "(<workspace>/channels/whatsapp/session.db)."
        ),
    )
