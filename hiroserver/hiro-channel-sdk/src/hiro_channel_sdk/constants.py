"""Channel SDK protocol constants.

Authoritative source for the JSON-RPC wire protocol, WebSocket close codes,
auth roles, message content types, and reconnect policy used by all Hiro
channel packages and the Hiro/Gateway servers.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# JSON-RPC
# ---------------------------------------------------------------------------

JSONRPC_VERSION: str = "2.0"
JSONRPC_ERROR_METHOD_NOT_FOUND: int = -32601
JSONRPC_ERROR_INTERNAL: int = -32603
JSONRPC_ERROR_CALL_REFUSED: int = -32000  # channel.call refused on purpose; data.reason says why

# ---------------------------------------------------------------------------
# Channel RPC methods
# ---------------------------------------------------------------------------

METHOD_REGISTER: str = "channel.register"
METHOD_RECEIVE: str = "channel.receive"
METHOD_EVENT: str = "channel.event"
METHOD_SEND: str = "channel.send"
METHOD_CONFIGURE: str = "channel.configure"
METHOD_STOP: str = "channel.stop"
METHOD_STATUS: str = "channel.status"
# core → plugin: a named request the plugin answers (params {"name", "params"}).
# Unlike channel.send (a reply the core hands over and forgets), the core waits for
# the answer: Phase 4's sends for an extension report "sent" or why not.
METHOD_CALL: str = "channel.call"

# Calls the WhatsApp plugin answers (channel.call names).
WHATSAPP_CALL_SEND: str = "send"    # {to, text?, image_b64?, voice_b64?, voice_seconds?, waveform_b64?} → {"sent": true}
WHATSAPP_CALL_CHECK: str = "check"  # {numbers: [...]} → {"answers": [{query, on_whatsapp, jid}]}

# ---------------------------------------------------------------------------
# WebSocket close codes (Hiro application range 4000–4999)
# ---------------------------------------------------------------------------

WS_CLOSE_NORMAL: int = 1000
WS_CLOSE_AUTH_FAILED: int = 4003
WS_CLOSE_PAIRING_FIELD_MISSING: int = 4004
WS_CLOSE_DESKTOP_NOT_CONNECTED: int = 4006
WS_CLOSE_PAIRING_TIMEOUT: int = 4008
WS_CLOSE_DUPLICATE_DEVICE: int = 4009
WS_CLOSE_CHANNEL_REPLACED: int = 4010
WS_CLOSE_EXTENSION_DENIED: int = 4011    # extension sign-in or pairing refused
WS_CLOSE_EXTENSION_REPLACED: int = 4012  # a newer connection of the same extension took over
WS_CLOSE_EXTENSION_REMOVED: int = 4013   # the extension was removed in the core's admin

# ---------------------------------------------------------------------------
# Extensions — programs that connect to the core on their own (HomeHiro first)
#
# Unlike a channel plugin, the core doesn't start an extension, so it signs in:
#   1. core → extension   {"type": "auth_challenge", "nonce": "<hex>"}
#   2. extension → core   {"type": "pair", "code", "public_key", "signature", "info"}   first time
#                         {"type": "auth", "extension_id", "signature", "info"}          after that
#      ``signature`` = the nonce signed with the extension's own Ed25519 key.
#   3. core → extension   {"type": "welcome", "extension_id", "core": {...}}
#                      or {"type": "denied", "reason", "message"} and the socket closes
# After the welcome both sides exchange UnifiedMessage frames: requests, responses
# and events (the device language), on routing.channel EXTENSION_CHANNEL.
# ---------------------------------------------------------------------------

EXTENSION_FRAME_CHALLENGE: str = "auth_challenge"
EXTENSION_FRAME_PAIR: str = "pair"
EXTENSION_FRAME_AUTH: str = "auth"
EXTENSION_FRAME_WELCOME: str = "welcome"
EXTENSION_FRAME_DENIED: str = "denied"

# Reasons carried by a "denied" frame.
EXTENSION_DENIED_NOT_PAIRED: str = "not_paired"        # unknown extension_id (never paired, or removed)
EXTENSION_DENIED_BAD_CODE: str = "bad_code"            # pairing code wrong or expired
EXTENSION_DENIED_BAD_SIGNATURE: str = "bad_signature"  # challenge signature didn't verify
EXTENSION_DENIED_BAD_FRAME: str = "bad_frame"          # first frame unreadable or incomplete

EXTENSION_CHANNEL: str = "extension"  # routing.channel on every extension message
CORE_SENDER_ID: str = "server"        # routing.sender_id on messages the core sends (same as to devices)

# Request methods every extension and the core answer (Phase 3's test calls).
METHOD_CORE_INFO: str = "core.info"            # extension → core: the core's name and version
METHOD_EXTENSION_INFO: str = "extension.info"  # core → extension: the extension's name and version

# Requests an extension makes of the core's WhatsApp (Phase 4: HomeHiro's messages go
# out through the core). Extensions only; errors come back as ExtensionRequestError
# with one of the WHATSAPP_ERROR_* codes (or invalid_params / internal_error).
#   whatsapp.send    {to, text?, image_b64?, voice_b64?, voice_seconds?, waveform_b64?, transcript?}
#                    → {"sent": true}. `to` = digits with country code, or a JID. One of: text,
#                    image (text = caption), voice (OGG/Opus; seconds and the 64-byte waveform are
#                    what WhatsApp shows). `transcript` is what a voice note says: never sent, only
#                    written to the owner's conversation when `to` is the owner's number.
#   whatsapp.check   {numbers: [...]} (at most WHATSAPP_CHECK_MAX) → {"answers": [{query, on_whatsapp, jid}]}
#   whatsapp.status  {} → {"running", "state", "detail", "waiting_for_link", "account"}; state is the
#                    plugin's last report ("" none yet): connected, paired, reconnecting, disconnected,
#                    logged_out, banned, error, replaced.
METHOD_WHATSAPP_SEND: str = "whatsapp.send"
METHOD_WHATSAPP_CHECK: str = "whatsapp.check"
METHOD_WHATSAPP_STATUS: str = "whatsapp.status"
WHATSAPP_CHECK_MAX: int = 20
WHATSAPP_ERROR_NOT_RUNNING: str = "whatsapp_not_running"      # the plugin isn't connected to the core
WHATSAPP_ERROR_NOT_CONNECTED: str = "whatsapp_not_connected"  # the plugin runs, but WhatsApp isn't linked/online
WHATSAPP_ERROR_FAILED: str = "whatsapp_failed"                # WhatsApp refused or the send failed

EXTENSION_AUTH_TIMEOUT_SECONDS: float = 10.0
EXTENSION_REQUEST_TIMEOUT_SECONDS: float = 15.0

# ---------------------------------------------------------------------------
# Auth roles
# ---------------------------------------------------------------------------

AUTH_ROLE_DESKTOP: str = "desktop"
AUTH_ROLE_DEVICE: str = "device"

# ---------------------------------------------------------------------------
# Message types — communication intent discriminator on UnifiedMessage
# ---------------------------------------------------------------------------

MESSAGE_TYPE_MESSAGE: str = "message"    # content exchange (text, images, files…)
MESSAGE_TYPE_EVENT: str = "event"        # fire-and-forget server→device (or device→server) signal
MESSAGE_TYPE_REQUEST: str = "request"    # reserved — expects a response
MESSAGE_TYPE_RESPONSE: str = "response"  # reserved — answer to a request
MESSAGE_TYPE_STREAM: str = "stream"      # reserved — streaming chunks

# ---------------------------------------------------------------------------
# Event types — type values used in EventPayload
# ---------------------------------------------------------------------------

EVENT_TYPE_MESSAGE_RECEIVED: str = "message.received"          # server acknowledged receipt of a message
EVENT_TYPE_MESSAGE_TRANSCRIBED: str = "message.transcribed"    # transcript is ready for a voice message (audio → text modality mirror)
EVENT_TYPE_MESSAGE_VOICED: str = "message.voiced"              # spoken audio of a text reply (text → audio modality mirror)
EVENT_TYPE_MESSAGE_CONTENT_ADDED: str = "message.content_added"  # new supplementary content attached to a message (photos, docs, etc.)
EVENT_TYPE_RESOURCE_CHANGED: str = "resource.changed"          # hint: named cache invalidated — pull via *.list / *.get (Tier 1+ sync substrate)

# ---------------------------------------------------------------------------
# Message content types — content_type values used in ContentItem
# ---------------------------------------------------------------------------

CONTENT_TYPE_TEXT: str = "text"
CONTENT_TYPE_JSON: str = "json"
CONTENT_TYPE_IMAGE: str = "image"
CONTENT_TYPE_AUDIO: str = "audio"
CONTENT_TYPE_VIDEO: str = "video"
CONTENT_TYPE_FILE: str = "file"
CONTENT_TYPE_LOCATION: str = "location"

# ---------------------------------------------------------------------------
# Reconnect / backoff policy
# ---------------------------------------------------------------------------

RECONNECT_DELAY_SECONDS: float = 5.0
RECONNECT_BACKOFF_BASE: float = 1.0
RECONNECT_BACKOFF_MAX: float = 60.0
