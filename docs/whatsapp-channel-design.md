# WhatsApp Channel — High-Level Design

> **Scope.** Add a **WhatsApp channel** so a user can talk to their Hiro character over
> WhatsApp with **text and voice notes**, both directions. This is a **high-level design**:
> it fixes the architecture, the main workflows, and the component boundaries. Fine details
> (exact config keys, error/retry policy, identity-mapping edge cases) are deliberately left
> to the implementation phase.
>
> **Decision (locked by product):** use an **unofficial WhatsApp Web library**, *not* the
> Meta WhatsApp Business Cloud API (too expensive for regular users + business-verification
> paperwork). Trade-off accepted: this runs against WhatsApp's ToS and carries **account-ban
> risk**, and unofficial libraries are **brittle** across WhatsApp updates. The design confines
> that risk to one swappable component.
>
> **Decision (locked by product):** the client must be **Python**, not Node.js. Chosen library:
> **[neonize](https://github.com/krypton-byte/neonize)** — Python bindings over the Go
> `whatsmeow` multi-device library, shipped as prebuilt wheels (`pip install neonize`).
>
> **Companions:** [Channel Plugins](../../hiro-docs/mintdocs/architecture/concepts/channel-plugins.mdx)
> (plugin subprocess model + JSON-RPC contract), [Agent Graph](../../hiro-docs/mintdocs/architecture/concepts/agent-graph.mdx)
> (STT → LLM → TTS pipeline this reuses), [network-topology](../../hiro-docs/mintdocs/architecture/concepts/network-topology.mdx).
>
> **Mode:** initial development — **no backward compatibility / no migration / no wrappers** (repo rule, abided).
>
> **Status:** Design draft. Not yet implemented.

---

## 1. The one-paragraph version

A WhatsApp channel is a **new channel plugin**, and the Hiro side already gives us everything
except the WhatsApp link itself: channels are subprocesses that speak JSON-RPC to the
`ChannelManager`, and the **STT (inbound audio) and TTS (outbound audio) pipeline already
exists and is channel-agnostic** — replies auto-route back to whatever channel the message
came in on. The only genuinely new thing is the WhatsApp connection, and **neonize** lets us
build it as a **single ordinary Python plugin**: it wraps the Go `whatsmeow` library (same
multi-device protocol as the well-known Node libraries) behind a prebuilt wheel with a native
**asyncio** client, so it drops straight into the plugin's existing async transport. No Node,
no sidecar, no extra process. All WhatsApp-specific brittleness/ban risk lives behind the
neonize client object, which we treat as a swappable adapter.

---

## 2. Key decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Provider | **Unofficial WhatsApp Web library** | Business API too costly + paperwork (product decision). |
| Language | **Python** | Product decision; reuses `hiro-channel-sdk` and the whole channel pattern with zero language split. |
| Library | **neonize** | Actively maintained Python wrapper over Go `whatsmeow` — the same multi-device / E2EE / QR-pair protocol the Node libs use. Native **asyncio** client (`NewAClient`), sends/receives text + media + **voice notes**, prebuilt wheels for Windows/macOS/Linux (`pip install neonize`). No Go toolchain, no Node. |
| Plugin topology | **Single Python plugin** (`ChannelPlugin` subclass) | neonize removes the need for a Node sidecar — one process, standard `uv`-installed plugin like every other channel. |
| Distribution | **First-party but *optional*** | Authored/maintained by us, but **not mandatory** like `devices`; the user opts in. |
| Dependency isolation | **Heavy deps (`neonize`, `ffmpeg`) installed only on opt-in** | Channels are separate packages in separate envs; `hirocli` depends on no channel, so nothing pulls WhatsApp deps unless the user adds this channel. |
| Activation | **Hot spawn/stop — no restart** | `ChannelManager` gains `activate(name)`/`deactivate(name)`; a newly-enabled channel comes alive live. |
| Onboarding | **CLI *and* Admin UI**, both over the same channel Tools | Reuse existing `ChannelSetupTool`/`ChannelEnableTool`/… per the Tools Architecture; UI owns configure/enable/pair/status. |
| Auth | **QR / pair-code** login, surfaced in **Admin UI** | Standard WhatsApp Web linking; neonize persists session so re-login is rare. |
| Session store | **SQLite** under the workspace | neonize's default; one file, no external DB needed. |
| Audio inbound | **Pass through to existing STT** | WhatsApp voice notes are OGG/Opus — already accepted by OpenAI/Gemini STT. No transcoding. |
| Audio outbound | **Transcode TTS → OGG/Opus** before `send_audio(ptt=True)` | WhatsApp native voice notes require OGG/Opus; TTS emits MP3. `ffmpeg` invoked in-process. |

**Why neonize over the Node libraries:** the underlying engine (`whatsmeow`) is the same class
of multi-device client as Baileys — same protocol, same personal-account support, same QR
pairing — but neonize exposes it to Python directly. That collapses what would have been a
two-language, two-process design into one plugin that looks like every other channel in the
repo.

---

## 3. Architecture

```mermaid
flowchart TB
    User["WhatsApp user<br/>(text / voice note)"]

    subgraph Plugin["hiro-channel-whatsapp (new, pure Python)"]
        direction TB
        SDK["ChannelPlugin (hiro-channel-sdk)<br/>register · configure · emit · send · events"]
        Neo["neonize NewAClient (asyncio)<br/>wraps Go whatsmeow<br/>WA socket · QR · media · session"]
        Trans["translation + identity map<br/>UnifiedMessage ↔ WA · ffmpeg"]
        SDK <--> Trans <--> Neo
    end

    subgraph Server["Hiro Server (existing, reused)"]
        CM["ChannelManager"]
        Comm["Communication Mgr<br/>+ outbound pipeline"]
        Graph["Agent Graph<br/>STT → LLM → TTS"]
    end

    Admin["Admin UI<br/>(install/configure + QR + status)"]

    User <-->|"WhatsApp Web multi-device protocol"| Neo
    SDK <-->|"JSON-RPC / WS<br/>register · configure · receive · send · event"| CM
    CM --> Comm --> Graph
    Graph -->|"reply + message.voiced"| Comm
    Comm -->|"send_to_channel('whatsapp')"| CM --> SDK
    CM -.->|"config + QR/status events"| Admin
```

One process, one language. The `neonize` client is the only WhatsApp-aware part — if the
library breaks or we swap it, only the code touching `NewAClient` changes.

---

## 4. Main workflows

### 4.1 Pairing / login (QR)

First run has no saved session, so the user links the device by scanning a QR (like WhatsApp
Web). neonize surfaces the QR via its event stream; we forward it to the Admin UI.

```mermaid
sequenceDiagram
    participant Admin as Admin UI
    participant CM as ChannelManager
    participant Plugin as WhatsApp plugin
    participant Neo as neonize (whatsmeow)
    participant WA as WhatsApp

    Note over Plugin,Neo: on_start — no saved session
    Plugin->>Neo: NewAClient(session.db).connect()
    Neo->>WA: begin multi-device login
    WA-->>Neo: QR challenge
    Neo-->>Plugin: PairStatus / QR event
    Plugin-->>CM: emit_event("whatsapp.qr", {qr})
    CM-->>Admin: render QR
    Admin-->>Admin: user scans QR with phone
    WA-->>Neo: paired + credentials
    Neo->>Neo: persist session to SQLite
    Neo-->>Plugin: Connected event
    Plugin-->>CM: emit_event("whatsapp.status", {state:"connected"})
    CM-->>Admin: show "Connected"
```

On later restarts the saved SQLite session skips the QR and reconnects silently.

### 4.2 Inbound — text and voice

```mermaid
sequenceDiagram
    participant WA as WhatsApp user
    participant Neo as neonize
    participant Plugin as WhatsApp plugin
    participant CM as ChannelManager
    participant Graph as Agent Graph (STT→LLM→TTS)

    WA->>Neo: message (text OR voice note = OGG/Opus)
    Neo-->>Plugin: @event(MessageEv)
    alt voice note
        Plugin->>Neo: download_media(event)
        Neo-->>Plugin: audio bytes (OGG/Opus)
        Plugin->>Plugin: ContentItem(content_type="audio", mime, duration, b64)
    else text
        Plugin->>Plugin: ContentItem(content_type="text", body)
    end
    Plugin->>Plugin: map WA sender JID → Hiro user/character
    Plugin->>CM: emit(UnifiedMessage, direction=inbound, channel="whatsapp")
    CM->>Graph: deliver
    Note over Graph: voice → stt_node transcribes → LLM sees text<br/>(existing, unchanged)
```

Inbound audio needs **no transcoding** — OGG/Opus is already a format STT accepts.

### 4.3 Outbound — text reply and voice reply

The reply inherits `routing.channel = "whatsapp"` from the inbound message, so the outbound
pipeline dispatches it to our `send()` automatically — the generic path every channel uses
(`send_to_channel(msg.routing.channel, …)`).

```mermaid
sequenceDiagram
    participant Graph as Agent Graph
    participant Comm as Outbound pipeline
    participant CM as ChannelManager
    participant Plugin as WhatsApp plugin
    participant Neo as neonize
    participant WA as WhatsApp user

    Graph->>Comm: text reply (message)
    Graph->>Comm: TTS audio (event: message.voiced, MP3 b64)
    Comm->>CM: send_to_channel("whatsapp", envelope)
    CM->>Plugin: send(envelope)
    alt message.voiced event
        Plugin->>Plugin: ffmpeg MP3 → OGG/Opus
        Plugin->>Neo: send_audio(recipient, ogg, ptt=true)
        Neo->>WA: voice note bubble
    else text message
        Plugin->>Neo: send_message(recipient, text)
        Neo->>WA: text
    end
```

The one non-trivial step is the **MP3 → OGG/Opus transcode** before `send_audio(ptt=True)` so
the reply renders as a native voice bubble rather than a file attachment.

---

## 5. Distribution & activation model

- **First-party but optional.** The plugin is authored and maintained by us, but it is **not a
  mandatory channel** — unlike `devices`, which is special-cased via `MANDATORY_CHANNEL_NAME`
  and always active. WhatsApp is present only when the user chooses it.
- **Per-plugin dependency isolation.** Channels are separate packages that run as their own
  subprocesses in their own environments; `hirocli` does not depend on any channel package.
  Therefore `neonize` and `ffmpeg` are **only** pulled in when a user opts into WhatsApp — a
  user who never adds it pays nothing.
- **Packaging.** WhatsApp's heavy dependencies (`neonize`, `ffmpeg`) are gated behind an
  **optional dependency extra** so they install only on opt-in. (Extra-on-a-bundled-package vs
  a fully separate installable package is the remaining packaging detail — see §10.)
- **Hot activation — no restart.** `ChannelManager` exposes `activate(name)` / `deactivate(name)`
  so enabling a channel spawns its subprocess live, and disabling it sends `channel.stop` and
  reaps the process. The scaffolding already exists (`_spawn_one`, the plugin WebSocket server,
  `_push_config`, event emission); on-demand activation exposes it outside startup.
- **Live reconfigure.** Config changes to a running plugin are pushed via `channel.configure`
  (`_push_config`) without a restart.

---

## 6. Installation, onboarding & lifecycle

### 6.1 Three independent actions

Onboarding is composed of three distinct steps; each is separately triggerable and separately
failable, and **none requires a server restart**:

| Step | Action | Trigger |
|------|--------|---------|
| **A. Install** | Ensure the package + deps are present (optional extra, or a curated first-party package install) | CLI or Admin UI |
| **B. Activate** | Spawn the plugin subprocess so it connects (`ChannelManager.activate`) | CLI or Admin UI |
| **C. Pair** | Scan the QR to link the WhatsApp account | Admin UI (QR event) |

### 6.2 Target onboarding flow (fully live)

```mermaid
flowchart LR
    A["Install / ensure deps<br/>(no-op if extra already present)"]
    --> C["Configure<br/>(session, character, allow-list, audio)"]
    --> E["Enable"]
    --> S["ChannelManager.activate()<br/>hot-spawn subprocess"]
    --> Q["Scan QR in UI<br/>(whatsapp.qr event)"]
    --> R["Ready ✓ — live status"]
```

Because neonize persists its session to SQLite, hot-spawn is primarily a **first-run** nicety;
after pairing, a normal restart reconnects silently.

### 6.3 Channel lifecycle state machine

Channel status is modeled as a **state machine**, not a single `enabled` boolean, so each
failure is visible and the UI can reflect exactly where a channel is:

```mermaid
stateDiagram-v2
    [*] --> Installed
    Installed --> Configured
    Configured --> Enabled
    Enabled --> Spawned : activate()
    Spawned --> Connected
    Connected --> Paired : QR scanned
    Paired --> Ready
    Ready --> [*]
    Spawned --> Error : dep missing / bad config
    Connected --> Error : WA unreachable
    Paired --> Error : logged out / banned
    Error --> Enabled : retry
```

### 6.4 Onboarding surfaces

- **CLI and Admin UI both drive the same channel Tools** (`ChannelSetupTool`,
  `ChannelEnableTool`, `ChannelDisableTool`, `ChannelListTool`, `ChannelRemoveTool`) — per the
  Tools Architecture, one Tool backs CLI + HTTP + UI.
- **Admin UI owns** configure, enable/disable, pair (QR), and live status. **Install** is an
  optional-convenience button (curated first-party package) or handled by the optional extra.
- **HTTP endpoints** expose the channel Tools to the Admin UI (config writes go through the
  server that owns `workspace.db`, like Preferences).
- **Feature-flag** the Admin page via the codegen'd feature ledger
  (`features.py` → `feature-registry.json`) so it ships hidden until ready.

---

## 7. Component responsibilities

| Component | Owns | Does **not** own |
|-----------|------|------------------|
| **WhatsApp plugin** (single Python `ChannelPlugin`) | Register/configure/start/stop; drive `neonize.NewAClient`; `emit()` inbound; `send()` outbound; UnifiedMessage ↔ WhatsApp translation; sender-JID → Hiro-identity mapping; ffmpeg transcode; forward QR/status via `emit_event`. | The core server contract; STT/TTS (reused). |
| **neonize client** (dependency) | WhatsApp socket, QR login, session persistence, send/receive, media download/upload, reconnect. | Anything Hiro-specific. |
| **ChannelManager** | Spawns/stops plugins, JSON-RPC transport, pushes config, routes outbound. **New:** `activate(name)`/`deactivate(name)` hot spawn/stop. | — |
| **Channel config API** | Server-owned write of the `channel_plugins.config` JSON + HTTP endpoints exposing the channel Tools. **New:** a config editor (today `channel setup` sets only the launch command + enabled — there is no path to set `config` keys yet). | — |
| **Agent Graph** (existing) | STT, LLM, TTS. | — |
| **Admin UI** | Install (optional) / configure / enable / pair (QR) / live status. | — |

---

## 8. Config, identity, and session state

- **Config** (stored in `workspace.db::channel_plugins.config`, edited via the new config
  editor / Admin UI): session-DB path, default character to route to, allow-list of permitted
  WhatsApp numbers (so strangers can't talk to your agent), audio on/off toggles. Exact keys TBD.
- **Identity mapping:** neonize delivers a sender JID (`<number>@s.whatsapp.net`). The plugin
  maps it to a Hiro user + character. **Open question** (§10): 1:1 number→character, a routing
  table, or first-contact provisioning.
- **Session persistence:** neonize stores the linked-device session in a **SQLite DB** under
  the workspace (e.g. `<workspace>/channels/whatsapp/session.db`). Present + linked ⇒ no QR on
  restart. Deleting it forces fresh QR pairing (the "log out / re-link" operation).

---

## 9. Audio format handling (summary)

| Direction | WhatsApp format | Hiro pipeline | Action |
|-----------|-----------------|---------------|--------|
| Inbound voice | OGG/Opus | STT accepts OGG/Opus | **Pass through**, no transcode |
| Outbound voice | needs OGG/Opus (PTT) | TTS emits MP3 (OpenAI) / OGG (Gemini) | **Transcode MP3 → OGG/Opus**, then `send_audio(ptt=True)` |

`ffmpeg` becomes a runtime dependency of the plugin (invoked directly from Python — no separate
process to manage beyond the ffmpeg call). Fallback if we want to defer transcoding: send the
MP3 as a plain audio **document**, which shows as a file rather than a native voice bubble.

---

## 10. Open questions (defer to implementation)

1. **Identity/routing:** how WhatsApp numbers map to users/characters, and how unknown senders
   are handled (ignore / allow-list / auto-provision).
2. **Multi-account:** one WhatsApp number per plugin instance, or several? (whatsmeow is
   one-session-per-client; multiple numbers ⇒ multiple plugin instances.)
3. **Groups:** support WhatsApp group chats, or 1:1 only for v1? (Recommend 1:1 first.)
4. **Transcode vs file** for outbound audio (native voice note vs audio file) — pick per §9.
5. **Ban-resilience:** reconnect/backoff policy, and detecting + surfacing a logged-out/banned
   session to the user.
6. **Packaging shape:** deps-as-extra on a bundled package vs a fully separate installable
   package; and how `ffmpeg` is provided (bundled vs system dependency documented in setup).
   Confirm neonize wheels cover the target OSes (esp. Windows).
7. **UI-triggered install:** offer an in-UI install button (curated first-party package only) as
   an optional convenience, or keep install to CLI / the optional extra.

---

## 11. Suggested phasing

1. **Phase 1 — text round-trip.** Python plugin skeleton wrapping `neonize.NewAClient` + QR
   login + config. Prove: WhatsApp text in → LLM → WhatsApp text out.
2. **Phase 2 — inbound voice.** Download voice note → `audio` ContentItem → existing STT
   transcribes → LLM replies (text). No new pipeline code expected.
3. **Phase 3 — outbound voice.** Handle `message.voiced` in `send()`, transcode to OGG/Opus,
   `send_audio(ptt=True)`.
4. **Phase 4 — operability.** Config editor + HTTP endpoints, `ChannelManager` hot spawn/stop,
   lifecycle-state surfacing, and the Admin UI channel page (install/configure/enable/pair/status).
5. **Phase 5 — hardening.** Allow-list, reconnect/ban handling, packaging + ffmpeg docs.

---

## 12. TL;DR

- **New channel plugin, single pure-Python process** using **neonize** (Python wrapper over Go
  `whatsmeow` — same multi-device protocol as the Node libs, native asyncio, `pip install`).
  No Node, no sidecar.
- **First-party but optional**, with `neonize`/`ffmpeg` **isolated per-plugin** (installed only
  on opt-in). Not mandatory like `devices`.
- **Onboarding is three independent, restart-free steps** — install, activate (hot spawn/stop),
  pair (QR) — driven from CLI **and** an Admin UI page over the existing channel Tools. Channel
  status is a **lifecycle state machine**, not a boolean.
- **Two new engine pieces:** `ChannelManager` **hot spawn/stop**, and a **config editor**
  (today only the launch command + enabled are settable; `config` keys are not).
- **STT/TTS and outbound routing already exist and are channel-agnostic** — we mostly wire, not
  build, the audio path.
- **Inbound voice is free** (OGG/Opus → STT). **Outbound voice** needs an MP3→OGG/Opus `ffmpeg`
  transcode before `send_audio(ptt=True)`.
- **Auth = QR** in Admin UI; session persisted to SQLite so re-login is rare.
- **Accepted risk:** unofficial lib ⇒ ban/brittleness, confined behind the neonize client.
- **Deferred (§10):** identity/routing, groups vs 1:1, multi-account, ban-resilience, packaging
  shape, UI-triggered install.
