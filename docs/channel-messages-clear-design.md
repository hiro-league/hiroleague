# Channel messages clear — design

> **Status:** Design — Phases **1 (server)** + **2 (Flutter)** + **3 (UI)** implemented.  
> **Audience:** implementers (server, admin UI, Flutter device).  
> **Scope:** Delete **all messages** in one conversation channel **without** deleting the channel. Propagate to devices via existing resource sync.

Canonical architecture lives in **hiro-docs** (`mintdocs`): [Message persistence](/architecture/concepts/message-persistence), [Device history sync](/architecture/concepts/message-persistence/device-history-sync), [Domain Event Bus](/architecture/concepts/domain-event-bus), [Communication Manager](/architecture/concepts/communication-manager). This file is the **product + contract** summary for this feature.

We are in **initial development**: no backward compatibility, migration, or shim layers unless explicitly required later.

---

## Implementation phases

| Phase | Scope | Deliverable |
|-------|--------|---------------|
| **1** | **Server only** | **Done:** `last_deleted` on `channels` + `clear_channel_messages` (DB + non-shared blob unlink, bump epoch, `channel.changed`), **`channels.list`** includes `last_deleted`, gateway **`channels.clear_messages`**, tool `conversation_channel_clear_messages`. |
| **2** | **Flutter device** | **Done:** On `channels.list` / `resource.changed:channels`, if `server.last_deleted` > locally applied epoch → wipe messages + non-shared blob files, clear history watermark (`appliedServerLastDeleted`), then `refreshChannels` replays `messages.history` for server-backed channels when any mirror was reset. |
| **3** | **UI** | **Done:** Admin Chat messages header button + Flutter channel settings button → **`channels.clear_messages`** (Admin wraps the same primitive via HTTP). |

Phase order avoids shipping UI without convergence (Phase 2) and avoids Flutter work before wire+epoch exist (Phase 1).

---

## 1. Goal

- Provide a **single server-side operation**: clear every message and its attachments for channel `C`, remove **non–cross-channel-shared** media files, **increment a server-only integer** on the channel row, notify devices, and expose that value on **`channels.list`**.
- **Admin UI** and **Flutter** invoke it via **explicit buttons** (§6).
- Devices **converge**: local Drift mirror + local blobs for that channel match the cleared server state, and **history sync restarts cleanly** for that channel after a **watermark reset**.

---

## 2. Assumptions

| # | Assumption |
|---|-------------|
| A1 | Anyone who can use the Admin UI or the Flutter app **may** invoke clear; no extra role matrix in this design. |
| A2 | **`last_deleted` (name TBD)** is an **integer epoch**; **only the server** increments it (e.g. within the same DB transaction as the delete). |
| A3 | **Any** conversation channel may be cleared — we remove **messages**, not the **channel** row. Distinct from channel delete. |
| A4 | Attachment bytes may be **shared across channels** by `blob_id`. When deleting files on disk, delete only blobs **not** referenced by remaining attachment rows in **other** channels. |
| A5 | **`messages.history`** semantics stay **incremental (after watermark)**; we do **not** change the core paging/upsert algorithm. Reconciliation is **orchestration**: epoch + local wipe + **clear per-channel history watermark** (see §5). |

---

## 3. Server behavior

### 3.1 Operation (atomic intent)

1. In one logical transaction (or equivalent isolation):
   - Delete **`message_attachments`** then **`messages`** for **`channel_id`** (existing FK/persistence patterns).
   - Remove or reconcile **media files** for those attachments, respecting **A4** (skip shared `blob_id`).
   - Set **`last_deleted := last_deleted + 1`** on the **channels** row for `C`. If the column is new, treat `NULL` as `0` before increment.
   - Update **`last_message_at`** (or equivalent channel metadata) per product rules — typically **cleared / null** after a full clear.
2. Publish **`channel.changed`** with `channel_id` so the [Domain Event Bus](/architecture/concepts/domain-event-bus) subscriber ([Resource Change Broadcaster](/architecture/concepts/communication-manager)) emits **`resource.changed`** for resource **`channels`** (existing mapping: `channel_changed` → `channels`).

### 3.2 API surfaces

- Implement **one** domain function used by:
  - Gateway **request** method (e.g. `channels.clear_messages` — exact name TBD), for Flutter.
  - Admin API route or tool invocation, for Control Room.
- No requirement in this doc whether Admin uses HTTP-only or the same JSON-RPC as devices; both must call the **same** server primitive.

### 3.3 **`channels.list`** payload

- Each channel object includes **`last_deleted`** (integer, default `0`). Devices compare this to their stored epoch per channel **after** merging the list.

---

## 4. Device behavior (Flutter)

### 4.1 Trigger

- On **`resource.changed`** with `resource == "channels"`, existing flow refetches **`channels.list`** (see `docs/resource-sync.md`).
- Also apply the same comparison when **`channels.list`** is refreshed for any other reason (connect, stale revalidation), so offline / missed hints still converge.

### 4.2 Reconcile rule

For each channel in the merged list:

If **`server.last_deleted` > `device_stored_last_deleted`** for that channel:

1. **Wipe local state for that channel**
   - Delete **messages** and **message attachment** rows for that channel in Drift.
   - Delete **local blob files** only when **no other** local attachment row still references the same `blob_id` (mirror **A4** on the client).
2. **Clear the per-channel history watermark / cursor** (`last_history_synced_*` fields for that channel — exact column names in implementation). Rationale: guarantees the next **`messages.history`** pass behaves like a **cold catch-up** per [Device history sync](/architecture/concepts/message-persistence/device-history-sync), avoiding edge cases where the cursor still points at IDs/timestamps no longer present upstream.
3. **Persist** `device_stored_last_deleted := server.last_deleted`.
4. Run the **normal** message-history sync for that channel (empty result until new server messages exist).

No change to **`messages.history`** request/response contract beyond what already exists.

### 4.3 Operator button (Flutter)

- The destructive action is triggered from **channel settings** (see §6.2), not from the chat header, so it stays out of the main send/read flow.

---

## 5. Why wipe + watermark clear (short)

| Issue | Without local wipe | With wipe + watermark clear |
|-------|--------------------|----------------------------|
| Server removed rows | Upsert-only history **never deletes** stale local rows; UI shows ghost messages. | Local rows removed; UI matches server. |
| Cursor after purge | Often still safe for **new** messages only, but keeping a stale cursor is subtle. | Cleared cursor ⇒ simple, documented “empty device / first load” semantics for that channel. |

---

## 6. Client UI — buttons

Both buttons call the **same** server primitive (§3.2). Recommend a **two-step destructive** pattern (modal or sheet: short explanation → confirm), even though detailed copy is implementation detail.

### 6.1 Admin UI — Chat messages page

| Item | Requirement |
|------|--------------|
| **Placement** | **Header** (or top app bar / page toolbar) of the **Chat messages** view — the screen that lists messages for the **currently selected channel**. |
| **Control** | One primary-affordance button, e.g. **“Clear messages”** / **“Delete all messages in channel”** (final label/copy TBD). |
| **Behavior** | On confirm: invoke Admin API (or shared backend path) → on success **refetch** the thread so the list is empty (§7). |

Implementation reference: packaged admin app under `hirocli` (`admin_frontend/` → `hirocli/admin_svelte/static/`); see `docs/admin-ui.md`.

### 6.2 Flutter — Channel settings page

| Item | Requirement |
|------|--------------|
| **Placement** | **Settings** screen for the channel (per-channel settings route/screen — not the main chat scaffold). |
| **Control** | Same semantic as Admin: one button triggering the gateway request (e.g. `channels.clear_messages`). |
| **Behavior** | On success: navigating back to chat should show an **empty** thread once local reconcile + **`channels.list`** / history sync catch up (§4); optionally **invalidate** providers for that channel immediately after success API response per app patterns. |

---

## 7. Post-action UX

| Client | Expected outcome |
|--------|-------------------|
| **Admin** | After succeed: **reload** / **refetch** the message list for that channel; it should be **empty** (no rows). |
| **Flutter** | After succeed: **`last_deleted`** path (§4) clears local mirror + watermark; chat UI reflects empty state without requiring a reinstall. |

---

## 8. Out of scope (this doc)

- Per-message tombstones, partial channel delete from this operation, or server-side “silent” deletes without bumping **`last_deleted`**.
- Audit logging / operator confirmation UX (recommended in implementation).

---

## TL;DR

- **Server:** delete all messages + non-shared blobs for channel, bump **`last_deleted`** integer only on server, fire **`channel.changed`** → **`resource.changed`** `channels`; expose epoch on **`channels.list`**.
- **Device:** on list merge, if server epoch newer → **delete local rows + non-shared blobs**, **clear history watermark**, store epoch → run normal **`messages.history`** loop.
- **Admin:** **header/toolbar button** on **Chat messages** page → same primitive → **refetch** thread.
- **Flutter:** button on **channel settings** page → gateway request → **§4** reconcile; **`messages.history`** unchanged; **incremental history** stays valid **after** a clean slate.
