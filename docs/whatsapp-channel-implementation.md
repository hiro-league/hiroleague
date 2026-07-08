# WhatsApp Channel — Implementation Plan

> **Companion to** [`whatsapp-channel-design.md`](whatsapp-channel-design.md). That doc owns the
> *what/why* (architecture, decisions, contracts, phasing index); this one owns the *how* —
> per-phase tasks, exact file paths / signatures, and acceptance criteria.
>
> **How to read this.** Phases are **vertical slices** (design §11); each ends at a testable
> milestone. The detail here is drafted for all 8 phases up front, but **P1 is a de-risking
> spike** — expect P3–P8 details to be refined once P1/P2 expose how `neonize` actually behaves.
>
> **Mode:** initial development — **no backward compatibility / no migration / no wrappers**
> (repo rule, abided). Per repo rules: add **code comments explaining the reason** for
> non-obvious changes; **prefer Tools Architecture** (CLI/HTTP/UI over one Tool) for new
> operations; follow **human-first structured logging**; move shared helpers to `hiro-commons`.
>
> **Status:** Plan draft. Not yet implemented.

---

## 0. Package layout & conventions

### 0.1 New plugin package (copy `hiro-channel-echo`)

```
hiroserver/channels/hiro-channel-whatsapp/
├── pyproject.toml                       # deps: hiro-channel-sdk, hiro-commons, neonize (+ ffmpeg at P7)
└── src/hiro_channel_whatsapp/
    ├── __init__.py
    ├── main.py                          # typer entry (identical shape to echo/main.py)
    ├── plugin.py                        # WhatsAppChannel(ChannelPlugin)
    ├── wa_client.py                     # neonize NewAClient wrapper (connect, QR, session, events)
    ├── translate.py                     # UnifiedMessage ↔ WhatsApp message mapping
    └── audio.py                         # ffmpeg MP3→OGG/Opus (P7)
```

`pyproject.toml` mirrors [`hiro-channel-echo/pyproject.toml`](../hiroserver/channels/hiro-channel-echo/pyproject.toml):
`name = "hiro-channel-whatsapp"`, `[project.scripts] hiro-channel-whatsapp = "hiro_channel_whatsapp.main:app"`,
deps add `neonize` (and, at P7, ffmpeg via system binary or `ffmpeg-python`).

### 0.2 Server-side changes (in `hirocli`)

These are **not** in the plugin package — they live in the server:

| Area | File | Phase |
|------|------|-------|
| Inbound conversation resolver (sender → chat channel) | `hirocli/.../runtime/` inbound path (Communication Manager) | P2 |
| Channel config editor (write `config` JSON) | new Tool + `admin_svelte/routes/` | P3 |
| Admin HTTP routes (install/setup/enable/config/qr/status) | `admin_svelte/routes/whatsapp_channel.py` | P4 |
| `ChannelManager.activate/deactivate` + status/QR cache | `runtime/channel_manager.py` | P5 |
| Feature flag `whatsapp_channel` | `domain/features.py` | P4 |

### 0.3 Plugin lifecycle contract (from `hiro_channel_sdk.base.ChannelPlugin`)

Abstract: `info` (property → `ChannelInfo`), `on_configure(config: dict)`, `on_start()`,
`on_stop()`, `send(message: UnifiedMessage)`. Helpers: `emit(UnifiedMessage)` (inbound → Hiro),
`emit_event(event: str, data: dict)` (status/QR → Hiro), `on_event(event, data)` (Hiro → plugin).
Entry point: `PluginTransport(plugin, hiro_ws).run()` — auto-reconnects. Lifecycle order:
`on_configure` → `on_start` → [`send`/`emit`] → `on_stop`.

---

## 1. Phase 1 — Link & receive (raw)

> **Status: DONE — verified live.** Package `hiroserver/channels/hiro-channel-whatsapp/`
> (`main.py`, `plugin.py`, `wa_client.py`). Confirmed on a real device: QR pair → `✅ paired`
> → `✅ connected` → inbound text logged (`⬇️ WhatsApp received … · text`). Session persists;
> reconnect loop re-links without a new QR. QR delivered as a PNG (`<session dir>/qr.png`,
> rewritten per rotation) since the code rotates ~every 20s and ASCII-in-a-log is unscannable.
>
> **Bring-up findings (important, feed P2+):**
> - **Protobuf isolation is mandatory.** neonize needs **protobuf 7.x**; the shared hiro
>   workspace venv is pinned to **protobuf 6.x** (transitive). They cannot coexist in one venv,
>   so the plugin **must run in its own environment** — dev: a dedicated venv
>   (`channels/hiro-channel-whatsapp/.venv`) that the channel `command` points at directly
>   (`workspace_dir=""`, no `uv run` wrapping); prod: the isolated `uv tool install` env. This
>   validates design §5 (per-plugin dependency isolation) — running channels via the shared
>   workspace venv does NOT work for neonize.
> - **`on_start` was gated on config.** The plugin transport only calls `on_start()` from the
>   `channel.configure` handler (`transport.py:171-175`), and the server's `_push_config` only
>   sent `configure` when the payload was non-empty. Fixed: `_push_config` now **always** sends
>   `channel.configure` (`channel_manager.py:447`) so config-less channels still start.
> - **QR API:** use `client.qr(handler)` where `handler(client, data_qr: bytes)` — **not**
>   `client.event(QREv)` (never dispatched for QR; neonize's default QR handler only prints to
>   the terminal via segno, which is lost under the plugin's `DEVNULL` stdout).
> - **Plugin log path:** the ChannelManager passes `--log-dir <workspace>/logs`, so the log is
>   `…/hiro/workspaces/default/logs/channel-whatsapp.log` (NOT `~/.hiro/logs`).
> - **LID addressing (feeds P2).** A live sender arrived as `…@lid` (WhatsApp's privacy
>   identifier), NOT `…@s.whatsapp.net`. So P2's identity/allow-list must handle **LID** JIDs,
>   not just phone numbers — use `MessageSource.SenderAlt` for the phone-number equivalent when
>   present, and reply to the chat JID as delivered. Do not assume `sender_id` is a phone number.

**Goal:** prove the hard/risky part first — a `neonize` client that logs in via QR, persists its
session, and surfaces inbound WhatsApp messages. No agent wiring yet.

**Confirmed neonize API (v0.4.1)** — use these exact names downstream:
- `from neonize.aioze.client import NewAClient` → `NewAClient(session_db_path)`; `await connect()`, `await idle()`, `await disconnect()`.
- Events `from neonize.aioze.events import QREv, PairStatusEv, ConnectedEv, DisconnectedEv, LoggedOutEv, MessageEv`; register via `client.event(EventType)(handler)`, handler called as `handler(client, event)`.
- `QREv.Codes[0]` = pairing string. `PairStatusEv.ID.User` = linked account. `MessageEv.Info.MessageSource.{Chat,Sender,IsFromMe,IsGroup}`, `MessageEv.Message.{conversation, extendedTextMessage.text, audioMessage}`.
- Addressing/media (P2/P6/P7): `from neonize.utils import build_jid, Jid2String`; `build_jid(phone) -> JID`; `send_message(to, text)`, `send_audio(to, file: str|bytes, ptt=True)`, `download_any(message) -> bytes`.

### Plugin tasks
- **Scaffold** the package from `hiro-channel-echo` (§0.1); `WhatsAppChannel.info` →
  `ChannelInfo(name="whatsapp", version="0.1.0", description="WhatsApp channel (neonize)")`.
- **`wa_client.py`** — wrap `neonize.aioze.client.NewAClient(session_db_path)`:
  - `on_start()`: build the client, register `@client.event(MessageEv)` → log the message; call
    `await client.connect()`.
  - **QR:** on the pair/QR event, `await self.emit_event("whatsapp.qr", {"qr": <string>})` **and**
    log it (P1 has no UI; render QR in the terminal/log or write a PNG to the workspace).
  - **Status:** on connect/paired, `emit_event("whatsapp.status", {"state": "connected"})`.
  - Session DB path defaults to `<workspace>/channels/whatsapp/session.db` (from `on_configure`
    later; hard-code a sane default now).
- **`on_configure`** — store config dict (session path); no-op fields for now.
- **`send()`** — stub (log "not implemented") — wired in P2.
- **`on_stop()`** — `await client.disconnect()`.

### Install & run (CLI)
```
hiro channel install whatsapp            # ChannelInstallTool → uv tool install hiro-channel-whatsapp
                                          #   (dev: --editable, or `hiro channel setup` with workspace_dir)
hiro channel setup whatsapp              # ChannelSetupTool → writes channel_plugins row (command, enabled)
hiro stop && hiro start                  # ChannelManager._spawn_channels spawns it
```

### Key APIs
- `ChannelInstallTool.execute(channel_name, package=None, editable=False)` →
  `hiroserver/hirocli/src/hirocli/tools/channel.py`
- `ChannelSetupTool.execute(channel_name, command, enabled=True, workspace=None)` — same file.
- `ChannelManager._spawn_one` / `_spawn_channels` → `runtime/channel_manager.py:137`.

### ✅ Acceptance
Scan the QR (from terminal/log), and a WhatsApp text sent to the linked number appears in the
plugin log. Restart the server → reconnects **without** a new QR (session persisted). No reply yet.

### Risks / notes
This phase validates the riskiest unknowns: neonize QR/pairing, SQLite session persistence, and
**neonize wheel availability on Windows**. If any of these fail, the whole approach is revisited
here — cheaply.

---

## 2. Phase 2 — Text round-trip

**Goal:** the core deliverable — text a WhatsApp number, the character replies over WhatsApp.

> **Status: implemented — pending live test.** Server: `resolve_or_create_channel_for_sender`
> (`conversation_channel.py`) + `_ensure_conversation` injected in `InboundPipeline.receive`
> (mutates the shared `msg` so both persist + agent-dispatch see `chat_channel_id`). Plugin:
> `_handle_inbound` maps text → `UnifiedMessage` and `emit()`s it (stashing the chat JID in
> `metadata.wa_chat_jid`); `send()` delivers text via `wa_client.send_text` → `send_message`.
> **Reply addressing needs no server change** — `_build_reply_envelope` copies inbound metadata
> onto the reply, so `wa_chat_jid` round-trips to `send()`. LID and PN JIDs both round-trip via
> `build_jid`. **Live round-trip confirmed.** LID follow-up: replies now target the
> **phone-number JID (`MessageSource.SenderAlt`)** rather than the `@lid` chat JID — sending to
> LID hit whatsmeow prekey-503 / "no signal session" failures and a corrupt
> `SendMessageReturnFunction` return. `send_text` also tolerates that neonize return-parse
> `DecodeError` (the message dispatches Go-side before the return is read).
>
> **Echo fix:** the server's inbound **mirror** (`graph_event_subscriber._mirror_user_message`)
> re-broadcasts the user message for *sibling-device* sync and relies on the gateway excluding
> the origin device. External channels have no such exclusion, so it echoed the user's own text
> back over WhatsApp. Now gated to the **devices** channel only (`MANDATORY_CHANNEL_NAME`) — fixes
> the echo for every external channel, not just WhatsApp. Mirror/graph tests green (12 passed).

### Plugin tasks (`translate.py`)
- **Inbound:** map `MessageEv` text → `UnifiedMessage`:
  ```python
  UnifiedMessage(
      routing=MessageRouting(
          channel="whatsapp", direction="inbound",
          sender_id=<wa_jid>, recipient_id="server",
          metadata={"wa_chat_jid": <wa_jid>},   # round-trips so send() can address the reply
      ),
      content=[ContentItem(content_type="text", body=<text>)],
  )
  ```
  then `await self.emit(um)`.
- **Outbound `send()`:** for `message.message_type == "message"` with a text `ContentItem`,
  resolve the recipient JID (from `routing.recipient_id`, falling back to
  `routing.metadata["wa_chat_jid"]`) and call `wa_client.send_message(jid, text)`.

### Server tasks — inbound conversation resolver (the crux)
`persist_inbound()` requires `routing.metadata["chat_channel_id"]`
(`domain/message_store.py:38`, via `resolve_chat_channel_from_metadata`,
`domain/conversation_channel.py:197`). A WhatsApp plugin cannot know that id, so add a
**server-side resolver** in the inbound path (Communication Manager, the `on_message` callback
`ChannelManager` invokes):

- If `routing.channel != devices` and no `chat_channel_id` in metadata:
  - Look up (or create) a `ConversationChannel` keyed by `(channel="whatsapp", sender_id)` —
    e.g. `name = f"WhatsApp {sender_id}"`.
  - Create via `create_channel(workspace_path, name=…, character_id=default_character_id(ws),
    user_id=get_default_user_id(ws))` (`domain/conversation_channel.py:226`,
    `domain/character.py:291`, `domain/data_store.py:264`).
  - Inject `routing.metadata["chat_channel_id"] = channel.id`, then continue to `persist_inbound`
    + agent dispatch.
- **Verify** the reply envelope carries `routing.recipient_id = <original sender_id>` (the WA
  JID). If not, thread the JID through the resolver so the outbound reply is addressable
  (fallback already covered by `metadata["wa_chat_jid"]`).

### ✅ Acceptance
Text the linked number → your default character replies over WhatsApp. Full text conversation,
persisted to a WhatsApp-named conversation under the default user.

---

### P2 polish (deferred, tracked here)

- **Delivery/read receipts.** Our linked device receives + replies but never sends WhatsApp
  delivery/read receipts, so the sender's message stays on a single gray tick. whatsmeow/neonize
  does not auto-mark read — call its receipt/`mark_read` API once the agent has handled an inbound
  message so the sender sees ✓✓ / blue. (Candidate for P2-polish or P8.)
- **`SendMessageReturnFunction` decode warning.** **Root cause narrowed (2026-07-08):**
  reproduced in **pure neonize** (isolated `NewAClient`+`connect`+`send_message`, zero Hiro code),
  so it is **not our plugin**. The message *is* delivered; only neonize's parse of its own send
  *return* fails. **Not** a protobuf runtime version issue — fails identically on protobuf 7.35.1
  and 7.34.1 (matching the gencode). Points to a defect inside neonize 0.4.1.post0 (Go-serialized
  return vs Python gencode drift, or an error payload returned). We hold a minimal repro. Next:
  try other neonize versions / dump the raw return bytes to classify / report upstream. Tolerated
  as a soft warning meanwhile (delivery unaffected).
- **Conversation display name.** Replace the placeholder `whatsapp:<jid>` name with the pushname
  / phone number (see P3 identity work).

---

## 3. Phase 3 — Settings / config editor

**Goal:** make behavior configurable, and **close the current gap** that channel `config` keys
have no editor (`channel setup` only sets `command` + `enabled`).

### Config schema (stored in `channel_plugins.config` JSON)
Define `WhatsAppChannelConfig` (pydantic), e.g.:

| Key | Type | Purpose |
|-----|------|---------|
| `session_db_path` | str | session location; **default now workspace-scoped** `<workspace>/channels/whatsapp/session.db` (moves off the P1 home-dir default, avoids cross-workspace collision) |
| `allowed_senders` | list[str] | permitted sender numbers (v1: one) |
| `owner_number` | str? | the user's **own** WhatsApp number — messages from it route to the default conversation (see routing task) |
| `default_character_id` | str? | character for new/self conversations (default: workspace default = Hiro) |
| `default_channel` | str? | conversation to route the owner's messages to (default: **General**) |
| `audio_in` | bool | accept inbound voice notes (P6) |
| `audio_out` | bool | reply with voice notes (P7) |

### Tasks
- **New Tool** `ChannelConfigSetTool` (surfaces `{"cli","http"}`) that writes `cfg.config` via
  `save_channel_config()` (`domain/channel_config.py:81`) and, if the channel is running,
  re-pushes via `ChannelManager._push_config` (`runtime/channel_manager.py:447`) →
  `channel.configure`. Mirror the Preferences PATCH shape
  (`admin_svelte/routes/preferences.py:117`, request `{"edits": {path: value}}`).
- **Enforce allow-list** in the plugin: drop inbound `MessageEv` from senders not in
  `allowed_senders`.
- **Workspace-scope the session:** push `session_db_path` under the workspace so the linked
  account (and `qr.png`) live with the rest of the workspace state, not in `~/.hiro`.
- **Identity routing (from P2 feedback):** in the server resolver
  (`resolve_or_create_channel_for_sender`), if the inbound sender matches `owner_number`
  (compare the phone number, accounting for LID vs PN — `SenderAlt`), route to the configured
  **`default_channel`** (default: **General**) with `default_character_id` (Hiro) instead of
  minting a per-sender channel. Non-owner senders keep their own conversation, but named by
  **pushname / phone number** rather than the raw `whatsapp:<jid>` placeholder.
- **Deferred (later phase):** a full **per-contact routing map** (different contacts →
  different characters/channels). v1 ships the single configurable default target only.

### ✅ Acceptance
Set the allowed sender + character in config; messages from that number are answered, unknown
numbers are ignored; a config change reaches the running plugin without a restart. Messages from
`owner_number` land in **General/Hiro**; the session DB lives under the workspace.

---

## 4. Phase 4 — Admin UI onboarding

**Goal:** install, configure, pair (QR in-browser), and manage WhatsApp entirely from the Admin UI.

### Backend tasks
- **Feature flag:** add to `domain/features.py:39`
  `FeatureSpec(id="whatsapp_channel", label="WhatsApp Channel", active=False, note=…)`;
  regenerate frontend registry: `cd admin_frontend && npm run gen:features`.
- **Routes:** new `admin_svelte/routes/whatsapp_channel.py` with a `whatsapp_channel_router`
  (pattern: `admin_svelte/routes/channels.py`). Endpoints (all `{ok,error,data}`):
  - `POST /whatsapp/install` → `ChannelInstallTool`
  - `POST /whatsapp/setup` → `ChannelSetupTool`
  - `POST /whatsapp/{enable,disable}` → Channel{Enable,Disable}Tool
  - `GET/PATCH /whatsapp/config` → `ChannelConfigSetTool` (P3)
  - `GET /whatsapp/status` and `GET /whatsapp/qr` → read the server's status/QR cache (P5)
  - Register in `admin_svelte/api.py:58`, gated: `if feature_active("whatsapp_channel"): api_router.include_router(whatsapp_channel_router)`.
- **QR/status cache:** the server caches the latest `whatsapp.qr` / `whatsapp.status` events
  (delivered to `ChannelManager`'s `on_event` callback, `runtime/channel_manager.py:348`) so the
  `GET /whatsapp/qr` and `/status` endpoints can serve them (poll or SSE).

### Frontend tasks
- A **Channels admin page** (Svelte, `admin_frontend`): install button, enable/disable,
  config form, **QR panel** (render the cached QR string as a scannable image), status badge.
  Gate the nav entry on the `whatsapp_channel` feature. (Follow `svelte-best-practice`.)

### ✅ Acceptance
From the Admin UI: install → configure → scan the QR in the browser → see "Connected". No terminal.

---

## 5. Phase 5 — Hot spawn/stop + lifecycle

**Goal:** enable/disable takes effect live (no restart), and status reflects a real lifecycle.

### Tasks
- **`ChannelManager.activate(name)` / `deactivate(name)`** (`runtime/channel_manager.py`):
  - `activate`: `load_channel_config` → `_spawn_one(cfg, hiro_ws)` → on plugin register,
    `_push_config`. Idempotent (no-op if already running); guard concurrent activate/deactivate.
  - `deactivate`: send `channel.stop` (`METHOD_STOP`) and reap the subprocess in
    `self._subprocesses[name]`.
  - Wire the enable/disable endpoints (P4) to call these instead of requiring a restart.
- **Lifecycle state machine** (design §6.3): maintain a per-channel state
  `installed → configured → enabled → spawned → connected → paired → ready` (+ `error`), updated
  from events (`channel.register` → connected; `whatsapp.status:paired` → ready; error events →
  error). Expose via `GET /whatsapp/status` and the `/channels` payload.

### ✅ Acceptance
Toggle enable in the UI → the channel connects live without a restart; the status badge advances
through the lifecycle states.

---

## 6. Phase 6 — Inbound voice

**Goal:** understand WhatsApp voice notes. No new pipeline code — reuse existing STT.

### Plugin tasks
- On an inbound audio `MessageEv`: `download_media(...)` via neonize → OGG/Opus bytes → base64.
- Build `ContentItem(content_type="audio", body=<b64>, metadata={"mime_type": "audio/ogg",
  "duration_ms": <int>, "size": <int>})` (constant `CONTENT_TYPE_AUDIO = "audio"`,
  `hiro_channel_sdk/constants.py`), wrap in `UnifiedMessage`, `emit()`.

### Why it "just works"
`media.ingest_node` splits the audio item and `media.stt_node`
(`runtime/agent_graph/nodes/media.py:171`) calls `STTService.transcribe(body, mime_type=…)`
(`services/stt/service.py`), which accepts **base64 / data-URI / URL** and **`audio/ogg`** among
its formats — so no transcoding on the way in.

### ✅ Acceptance
Send a WhatsApp voice note → the character transcribes it and replies (text at this phase).

---

## 7. Phase 7 — Outbound voice

**Goal:** reply with a native WhatsApp voice-note bubble.

### Plugin tasks (`send()` + `audio.py`)
- Handle `message.message_type == "event"` with `event.type == "message.voiced"`
  (`EVENT_TYPE_MESSAGE_VOICED = "message.voiced"`). Read `event.data`:
  ```python
  audio_b64 = message.event.data["audio"]          # base64 MP3 (audio/mpeg) from TTS
  mime      = message.event.data["mime_type"]
  # data also has: duration_ms, blob_id, media_path, audio_b64 (dup)
  ```
  (Envelope built by `graph_event_subscriber._build_voiced_envelope`,
  `runtime/graph_event_subscriber.py:866`.)
- **`audio.py`:** transcode MP3 → **OGG/Opus** via `ffmpeg`
  (`ffmpeg -i in.mp3 -c:a libopus -f ogg out.ogg`) with proper error handling + logging.
- Send via `wa_client.send_audio(jid, ogg_bytes, ptt=True)` (native voice note). Recipient JID
  from the voiced envelope's `routing.recipient_id` / `metadata["wa_chat_jid"]`.
- **Fallback:** if transcode fails, send the MP3 as a plain audio **document** (a file, not a
  voice bubble) and log a warning.

### Why the transcode is mandatory
A native voice note requires `audio/ogg; codecs=opus` + `PTT=true`; MP3-as-PTT is broken on
Android (design §9). So the transcode is not optional.

### ✅ Acceptance
Ask a question → the character answers with a playable WhatsApp voice-note bubble.

---

## 8. Phase 8 — Hardening

**Goal:** make it robust and shippable.

### Tasks
- **Reconnect/backoff:** mirror `hiro-channel-devices` (`plugin.py:133` exponential backoff,
  base 1s, max 60s) around the neonize connection loop; `emit_event` connection status.
- **Ban / logout detection:** on neonize `LoggedOut` (or repeated auth failure),
  `emit_event("whatsapp.status", {"state": "logged_out"})` → server sets `error` state → UI
  prompts re-pair (delete `session.db`).
- **Error surfacing:** map failures onto the §6.3 `error` transitions in the status endpoint/UI.
- **ffmpeg provisioning:** decide bundled vs system dependency; document in
  `mintdocs/build/first-time-setup.mdx` (repo rule). Confirm neonize wheels cover target OSes
  (esp. Windows).
- **Packaging:** finalize how `hiro-channel-whatsapp` is published/installed; smoke-test
  `hiro channel install whatsapp` clean.
- **Docs:** update mintdocs (channel-plugins page + a WhatsApp how-to) per the
  document-executed-plans rule.

### ✅ Acceptance
Kill the network / log the session out → the plugin recovers cleanly (or clearly reports
`logged_out` and guides re-pairing) with an accurate UI status.

---

## Appendix A — API quick reference

### Plugin SDK (`hiro-channel-sdk`)
| Symbol | Signature / shape |
|--------|-------------------|
| `ChannelPlugin` (ABC) | `info` prop; `on_configure(config)`, `on_start()`, `on_stop()`, `send(msg)`; helpers `emit(msg)`, `emit_event(event, data)`, `on_event(event, data)` |
| `ChannelInfo` | `name: str; version="0.1.0"; description=""` |
| `MessageRouting` | `id (uuid); channel; direction; sender_id; recipient_id=None; timestamp; metadata={}` |
| `ContentItem` | `content_type; body=""; metadata={}` |
| `EventPayload` | `type; ref_id=None; data={}` |
| `UnifiedMessage` | `message_type="message"; routing; content=[]; event=None` |
| Entry point | `PluginTransport(plugin, hiro_ws).run()` |
| Constants | `CONTENT_TYPE_AUDIO="audio"`, `CONTENT_TYPE_TEXT="text"`, `MESSAGE_TYPE_EVENT="event"`, `EVENT_TYPE_MESSAGE_VOICED="message.voiced"`, `EVENT_TYPE_MESSAGE_TRANSCRIBED="message.transcribed"` |

### Server (`hirocli`)
| Symbol | Location |
|--------|----------|
| `ChannelManager._spawn_one` / `_spawn_channels` / `_push_config` / `send_to_channel` / `send_event_to_channel` | `runtime/channel_manager.py:137 / 447 / 461 / 527` |
| `persist_inbound(workspace_path, msg) -> int` | `domain/message_store.py:38` |
| `resolve_chat_channel_from_metadata(ws, metadata)` (needs `chat_channel_id`) | `domain/conversation_channel.py:197` |
| `create_channel(ws, *, name, character_id, user_id=…) -> ConversationChannel` | `domain/conversation_channel.py:226` |
| `get_default_user_id(ws) -> int` | `domain/data_store.py:264` |
| `default_character_id(ws) -> str` | `domain/character.py:291` |
| `Channel{Install,Setup,Enable,Disable,List,Remove}Tool.execute(...)` | `tools/channel.py` |
| `load/save/list/list_enabled/delete_channel_config`, `ChannelConfig` | `domain/channel_config.py` |
| Admin routes + registration + `feature_active` gate | `admin_svelte/routes/channels.py`, `admin_svelte/api.py:34` |
| Preferences PATCH pattern (config-editor reference) | `admin_svelte/routes/preferences.py:117` |
| Feature ledger `FeatureSpec` / `feature_active` | `domain/features.py:23 / 78` |

### Audio contracts
| Direction | Shape |
|-----------|-------|
| Inbound (plugin builds) | `ContentItem(content_type="audio", body=<b64/data-URI/URL>, metadata={mime_type, duration_ms, size})` → `stt_node` transcribes |
| STT input | accepts base64 / data-URI / URL; formats incl. `audio/ogg`, `audio/mp4`, `audio/webm`, `audio/mpeg`, `audio/wav`, `audio/flac` |
| Outbound (plugin receives) | `UnifiedMessage(message_type="event", event=EventPayload(type="message.voiced", ref_id=<reply_id>, data={audio (b64 MP3), mime_type, duration_ms, blob_id, media_path}))` |

---

## Appendix B — Open questions & deferred (from design §10)

- **Open:** ban-resilience policy (P8); ffmpeg provisioning + neonize Windows wheels (P8);
  allow-list UX (P3).
- **Deferred (not v1):** WhatsApp **group chats**, **multiple accounts**.

---

## Appendix C — Cross-phase integration risks to confirm early

1. **Reply addressing:** confirm the outbound reply/voiced envelope carries the WA JID
   (`routing.recipient_id` or `metadata.wa_chat_jid`) so `send()` can target it (P2/P7).
2. **Inbound resolver:** the sender→chat-channel creation is a **server-side** change, not
   plugin-side — the plugin only sets `sender_id`/`channel` (P2).
3. **neonize on Windows:** wheel + session DB + QR must all work on the primary dev OS (P1).
4. **Enable/disable HTTP surface:** `ChannelEnableTool`/`ChannelDisableTool` may need a `surfaces`
   entry to be callable over HTTP (P4).
