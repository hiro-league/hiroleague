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

# Phase 5: the core uses Home.
#   extension.state  core → extension, {} → {"state": {...}}: what the extension knows right now
#                    (Home: who is where), as plain JSON with names, built live when asked (never
#                    stored). The core's agent tool hands it to Hiro as it is; the shape is the
#                    extension's own.
#   notify           extension → core, {to: [{person}], medium, text, style}
#                    → {"results": [{person, name, sent, error?}]}. Hiro tells people something:
#                    style "exact" sends `text` as it is, "character" has Hiro's character write it
#                    in its own voice from `text`. Hiro's own preferences decide text or a voice
#                    note. medium: NOTIFY_MEDIUM_WHATSAPP only for now. Since Phase 6 `person` is a
#                    person id from the core's family list (people.list); the core finds their
#                    number. Extensions only; a failed person doesn't stop the others.
METHOD_EXTENSION_STATE: str = "extension.state"
METHOD_NOTIFY: str = "notify"
NOTIFY_MEDIUM_WHATSAPP: str = "whatsapp"
NOTIFY_STYLE_EXACT: str = "exact"
NOTIFY_STYLE_CHARACTER: str = "character"
NOTIFY_MAX_RECIPIENTS: int = 10

# Phase 6: the family lives in the core.
#   people.list      extension → core, {} → {"people": [{person_id, name, calls_them, whatsapp,
#                    role_id}], "roles": [{role_id, name, built_in, says, rights}]}. whatsapp = digits with the
#                    country code ("" = none); calls_them "" = their name.
#   people.add       extension → core, {name, role_id, calls_them?, whatsapp?} → {"person": {...}}
#   people.update    extension → core, {person_id, name?, role_id?, calls_them?, whatsapp?}
#                    → {"person": {...}}; a field left out stays as it is.
#   roles.add        extension → core, {name} → {"role": {...}}
#   roles.rename     extension → core, {role_id, name} → {"role": {...}}
#   roles.remove     extension → core, {role_id} → {} (refused while someone has it)
#   Phase 9a: each role in people.list also carries ``says`` (one line on what it is for) and ``rights``: the
#                    right keys ("<feature>.<right>") the core grants it in the calling extension, from the features
#                    the extension declared (ExtensionInfo.features; hiro_channel_sdk.access checks them).
#   roles.import_rights extension → core, {roles: {role_id: {rights: [...], says?: str}}} → {"imported": [role_id]}:
#                    once, an extension's own grants from before Phase 9a; only fills roles the core has no rights
#                    for in this extension yet (and an empty ``says``), never overwrites what the admin set.
#                    Or {copy_from: "<another extension's name>"} (Phase 9b): an app taking features over from another
#                    gets, for each role with none here yet, its rights there in the features this app declares.
#   people.changed   core → every connected extension, an event with {}: read people.list again.
#                    Events aren't queued: an extension also reads the list when it connects.
#   A refused change answers error code "invalid_params" with the reason for people.
METHOD_PEOPLE_LIST: str = "people.list"
METHOD_PEOPLE_ADD: str = "people.add"
METHOD_PEOPLE_UPDATE: str = "people.update"
METHOD_ROLES_ADD: str = "roles.add"
METHOD_ROLES_RENAME: str = "roles.rename"
METHOD_ROLES_REMOVE: str = "roles.remove"
METHOD_ROLES_IMPORT_RIGHTS: str = "roles.import_rights"
EVENT_PEOPLE_CHANGED: str = "people.changed"

# core.info answers {name, version, workspace, admin_port, repo}: admin_port (Phase 7b) is the core's admin web port, so
# an extension can link to the admin (its own setting may say the address people reach it at, e.g. behind a proxy).
# Phase 7a: the core answers questions (docs/phase7a-ai-asks-design.md in hiroleague).
#   ai.ask       extension → core, {use, profile?, prompt, pictures?: [base64 JPEG], picture_labels?,
#                sound?: {b64, mime}, schema?, detail?, local_only?, timeout?, wait?}
#                → {text, profile_id, profile_name, provider, model, plan, ms, tokens, tokens_in,
#                tokens_out, cost, estimate, notes, tries}. `use` is the extension's own use id
#                (ExtensionInfo.uses); the core reads the profile picked for "<extension>:<use>".
#   ai.profiles  extension → core, {} → {"profiles": [...], "uses": {use id: profile id | None}}.
#   Errors (the response's error code): no_profile, budget, busy, failed, invalid.
METHOD_AI_ASK: str = "ai.ask"
METHOD_AI_PROFILES: str = "ai.profiles"
AI_ERROR_NO_PROFILE: str = "no_profile"  # no profile given and none picked for the use
AI_ERROR_BUDGET: str = "budget"          # every profile in the chain is over its limit
AI_ERROR_BUSY: str = "busy"              # wait=false and the plan tool is already answering as many as allowed
AI_ERROR_FAILED: str = "failed"          # every profile tried failed (the message says why)
AI_ERROR_INVALID: str = "invalid"        # the ask itself is wrong (no prompt, bad picture, bad schema)

# Phase 7b: the core speaks (voice profiles; hiroleague services/voice).
#   voice.speak     extension → core, {text, use? | profile?, person?, label?}
#                   → {ogg_b64, seconds, waveform_b64, cached, cost, profile_id, profile_name, provider,
#                   model, voice}. `use` is the extension's own voice use id (ExtensionInfo.voice_uses);
#                   the core speaks with the profile picked for "<extension>:<use>", or `profile` (an
#                   alert's or a Speak node's own pick). OGG/Opus, mono 48 kHz: ready for a WhatsApp voice
#                   note or a speaker. The same words in the same voice come from the core's clip cache.
#   voice.profiles  extension → core, {} → {"profiles": [{id, name, line}], "uses": {use id: profile id | None}}.
#   Errors (the response's error code): no_profile, invalid, failed.
METHOD_VOICE_SPEAK: str = "voice.speak"
# Phase 7b: an extension picks the profile one of its own declared uses asks with (saved in the core's
# ai.uses / voice.uses; profiles are edited only in the core's admin).
#   ai.uses.set / voice.uses.set  extension → core, {use, profile: id | null} → {use, profile}. Error: invalid.
METHOD_AI_USES_SET: str = "ai.uses.set"
METHOD_VOICE_USES_SET: str = "voice.uses.set"
METHOD_VOICE_PROFILES: str = "voice.profiles"
VOICE_ERROR_NO_PROFILE: str = "no_profile"  # no profile given and none picked for the use
VOICE_ERROR_INVALID: str = "invalid"        # the request itself is wrong (no text, too long, unknown person)
VOICE_ERROR_FAILED: str = "failed"          # the provider failed (the message says why)

# Phase 8: one sign-in (docs/phase8-one-sign-in-design.md in hiroleague). An extension's site sends a signed-out
# browser to the core's sign-in page (<admin>/sign-in?for=<extension name>&next=<path>); the core sends it back to
# the site the extension declared (offers.shows, kind "site") at <site>/api/auth/hiro?code=<one-time>&next=<path>.
#   auth.code        extension → core, {code} → {person_id, name, role_id, role_name}. One use, 60 s, only by the
#                    extension the code was made for. Error: invalid_code.
#   sign_in.start    core → extension, {method, client_id, redirect_uri, state} → {url}: where to send the browser
#                    to sign in (e.g. Home Assistant's login page). `method` is the id the extension offered.
#   sign_in.finish   core → extension, {method, code, client_id, redirect_uri} → {person_id}: who signed in, as a
#                    core person. Errors: not_linked (signed in, but not a person in the family list; the message
#                    says why, for people), failed.
# An extension offers a sign-in in offers.can_do: {"kind": "sign_in", "id": "home_assistant", "label": "Home
# Assistant"}; and its site in offers.shows: {"kind": "site", "title": "Home", "icon": "house",
# "url": "http://homehiro.local", "roles": []} (roles [] = every role).
METHOD_AUTH_CODE: str = "auth.code"
METHOD_SIGN_IN_START: str = "sign_in.start"
METHOD_SIGN_IN_FINISH: str = "sign_in.finish"
AUTH_ERROR_INVALID_CODE: str = "invalid_code"
SIGN_IN_ERROR_NOT_LINKED: str = "not_linked"
SIGN_IN_ERROR_FAILED: str = "failed"
OFFER_KIND_SIGN_IN: str = "sign_in"
OFFER_KIND_SITE: str = "site"
AUTH_CODE_SECONDS: int = 60

# The code reports keep a report for the core and each extension, from each one's repo (hiro-code-reports' R4).
#   core.info         also answers {repo}: the core's own repo, CORE_REPO.
#   extensions.list   extension -> core, {} -> {"extensions": [{extension_id, name, version, description, repo,
#                     connected}]}: every paired extension, as it last described itself (live while connected), repo
#                     its ExtensionInfo.repo ("" = not said). Extensions only.
METHOD_EXTENSIONS_LIST: str = "extensions.list"
CORE_REPO: str = "hiroleague"

# Phase 9b: extensions ask each other, through the core (never directly).
#   An extension offers what it answers in ExtensionInfo.offers: `knows` (questions) and `can_do` (actions), each
#   {"method": "<its request method>", "name": "...", "says": "..."}, and answers them with register_request().
#   extensions.ask  extension -> core, {to: "<extension name>", method, params?, timeout?} -> the asked extension's
#                   answer as it is. The core passes it on only when `to` is connected and offers `method`; the
#                   asked extension gets params plus ASKED_BY ("<asker's name>"). Errors: not_connected (to isn't
#                   connected), not_offered (to doesn't offer method), timeout, and the asked extension's own errors.
METHOD_EXTENSIONS_ASK: str = "extensions.ask"
ASKED_BY: str = "_asked_by"  # added to the params the asked extension gets: who asked
ASK_ERROR_NOT_OFFERED: str = "not_offered"
ASK_TIMEOUT_MAX_SECONDS: float = 60.0

# An app's LAN name, set up by the core (docs/site-names-design.md in hiroleague). The extension's address setting
# claims a name; the core checks it is free, publishes it on the LAN (mDNS) and points the web proxy at the port the
# extension listens on, then the extension declares http://<name> as its site (offers.shows).
#   sites.claim   extension -> core, {name, port} -> {name, url, published, proxied, note}. name: "<label>.hiro.local"
#                 or "<label>.local" (letters, digits, dashes). One name per extension: a new claim drops its old one.
#                 published / proxied say whether the mDNS name and the proxy entry are live (False on a core whose
#                 machine isn't set up for names: the claim is kept, note says why). Errors: invalid, taken.
METHOD_SITES_CLAIM: str = "sites.claim"
SITES_ERROR_INVALID: str = "invalid"
SITES_ERROR_TAKEN: str = "taken"
SITES_DOMAIN: str = "hiro.local"  # an app's name is <label>.hiro.local, or a one-word <label>.local

EXTENSION_AUTH_TIMEOUT_SECONDS: float = 10.0
EXTENSION_REQUEST_TIMEOUT_SECONDS: float = 15.0
# Largest frame on the extension socket, both ends. An AI ask (ai.ask, Phase 7a) carries up to 60
# pictures as base64; websockets' default of 1 MiB would close the connection on it.
EXTENSION_MAX_MESSAGE_BYTES: int = 64 * 1024 * 1024

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
