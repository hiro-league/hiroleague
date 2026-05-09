# Admin UI — Chat messages audio playback

> **Audience:** Implementers touching `admin_frontend/` and `hirocli` admin APIs.  
> **Scope:** Operators viewing conversation history on **Chat channels → Messages** and playing **user voice** and **agent TTS** attachments when stored on disk.  
> **Status:** Design (not necessarily implemented).

## 1. Goal

Expose persisted audio in the Messages view (`<audio controls>`) for:

| Source | Attachment row lives on… | Typical `metadata.source` |
|--------|--------------------------|---------------------------|
| User inbound voice | **User** message | `user_audio` |
| Agent TTS | **Agent text reply** (slot `0`) | `character_tts` |

Canonical storage / device contract: [`message-audio-history-storage.md`](./message-audio-history-storage.md), Mintlify **UnifiedMessage** / `messages.history`. This doc covers **admin HTTP + Svelte** only.

**No backward compatibility** required for admin list JSON unless explicitly decided.

## 2. Today vs target

| Area | Today | Target |
|------|--------|--------|
| **List API** `GET /api/chat-channels/{channel_id}/messages` | **`_sync_list`** — `messages` only, **no** attachment join (`ChatChannelsService`) | **`_sync_history`** with **`limit=None`** — same **`content[]`** shape as **`messages.history`** (refs + metadata, no inline bytes). |
| **Who else uses `_sync_list`?** | Admin + domain tests only; **`_sync_history`** already calls **`_sync_list`** then joins **`message_attachments`** once | Unchanged internals; admin stops bypassing history. **`MessageHistoryTool` / RPC** already use **`_sync_history`**. |
| **Bytes** | No admin stream route | **GET** returns file + **`Content-Type`** from **`media_type`** |
| **UI** [`ChatChannelsPage.svelte`](../admin_frontend/src/lib/features/chat-channels/ChatChannelsPage.svelte) | Flat `body` only | Text from **`content`** + optional **one** audio player (see §6) |

## 3. Architecture

```
ChatChannelsService.list_messages_all
    → _sync_history(wp, channel_id, limit=None)
    → JSON (content[] + message_pk) ──► UI
    → fetch GET …/media (with X-Hiro-Workspace) ──► blob URL ──► <audio>
```

Listing never embeds octets; same split as **`messages.history`**.

## 4. Backend

### 4.1 Use `_sync_history` as the single list path

Do **not** duplicate the attachment JOIN in a parallel “admin-only” query. Admin list = **`_sync_history`**.

**`message_pk` (integer `messages.id`) without a second JOIN:** inside **`_sync_history`**, each raw row already has **`row["id"]`** before **`_history_row`**. Today history output uses string **`id`** = **`external_id`** only. Add **`message_pk`** in that same loop (e.g. merge into the dict returned from **`_history_row`**, or pass **`row["id"]`** into **`_history_row`**). **Do not** post-process history JSON alone to recover PK — that would require another DB lookup.

Device clients that consume history can ignore **`message_pk`** if their contract stays string-`id`-centric; admin needs **`message_pk`** only if routing/docs want it (optional for media URL design that keys by **`external_id`** only).

### 4.2 Media GET

- Example: `GET /api/chat-channels/{channel_id}/messages/by-external/{external_id}/attachments/{slot}/media`
- Workspace header → assert message’s **`channel_id`** → resolve attachment → **`FileResponse`** via [`media_file_path`](../hiroserver/hirocli/src/hirocli/domain/message_attachments.py) / [`resolve_ref`](../hiroserver/hirocli/src/hirocli/domain/files_resolver.py) (`message_attachment:…`).

### 4.3 Errors

- Missing on-disk file → **404** (row exists, bytes gone).
- Wrong channel / no row → **404**.

### 4.4 Formats (MP3, WebM, …)

**Authoritative:** stored **`media_type`** and on-disk bytes. TTS is commonly **MP3**; **Flutter web** capture is often **WebM** (`audio/webm` / `video/webm`); other MIMEs follow [`audio_extension_for_media_type`](../hiroserver/hirocli/src/hirocli/domain/media_store.py). Serve **`Content-Type`** from DB; browser **`<audio>`** support varies by codec — no extra server transcoding in this design.

## 5. Frontend

- Types: match history **`content[]`** + **`message_pk`**.
- **`<audio src="/api/…">`** does **not** send **`X-Hiro-Workspace`**. Use **`fetch` + blob + `URL.createObjectURL`**, then **`revokeObjectURL`** on teardown.
- Transcript / duration from **`content`** / attachment **`metadata`** when present.

## 6. Product scope (now vs later)

- **Now:** expect **zero or one** audio attachment per message in the UI (first `content` item with **`content_type === "audio"`** or slot `0`). Schema and **`_history_row`** may still allow more — no need to optimize multi-audio UX yet.
- **Not in scope:** non-audio attachment UI; multiple distinct audio clips per bubble beyond “open but unused.”

## 7. Edge cases

- **Missing attachment in DB:** **`_sync_history`** does not invent rows — nothing to play. Same as device history.
- **Live-only voiced audio:** if there is **no** **`message_attachments`** row, admin has **nothing** to list/play; inline base64 on **`message.voiced`** is out of band for this design (admin is history + disk).

## 8. Checklist

- [x] `list_messages_all` → **`_sync_history`**, **`message_pk`** on history rows; tests in [`test_service.py`](../hiroserver/hirocli/src/hirocli/admin/features/chat_channels/tests/test_service.py).
- [x] Media **GET** in [`api.py`](../hiroserver/hirocli/src/hirocli/admin_svelte/api.py); channel check via [`ChatChannelsService.resolve_message_attachment_media`](../hiroserver/hirocli/src/hirocli/admin/features/chat_channels/service.py).
- [x] Admin types + **`ChatChannelsPage`** + [`ChatMessageAttachmentAudio.svelte`](../admin_frontend/src/lib/features/chat-channels/ChatMessageAttachmentAudio.svelte) (blob fetch).
- [ ] Optional: link from [`admin-ui.md`](./admin-ui.md).

## 9. References

- [`message-audio-history-storage.md`](./message-audio-history-storage.md), [`admin-ui.md`](./admin-ui.md)
- Mintlify: **UnifiedMessage**, **device history sync**
- [`persist_inbound`](../hiroserver/hirocli/src/hirocli/domain/message_store.py), [`_synthesize_and_send`](../hiroserver/hirocli/src/hirocli/runtime/agent_manager.py)
