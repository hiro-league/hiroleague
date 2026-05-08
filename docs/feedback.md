Important observation: Doc §8.3 says filename should be `<blob_hex>.<ext>` (not `<message_id>.<ext>`), so two messages sharing a blob share one file. But `saveBytes` uses `messageId` parameter as filename. The fetch service passes `_storageIdForBlob(blobId)` → strips `sha256:` prefix → so the stored file is named after the blob hex. Good. But for inbound live audio (`_handleInboundAudio` line 322), it passes `id` (message id), not blob hex. So inbound live audio files are named per message id, which is OK only if no dedup is expected for live messages. The history sync will then also fetch the blob separately (writing under blob hex). Two copies on disk for the same message.

I have enough now. Let me compose a comprehensive review.

## Review of `message-audio-history-storage.md` implementation

I went through every modified/new file in the design's scope (server: `domain/{data_store,message_store,message_attachments,files_resolver,media_store}`, `runtime/{agent_manager,request_methods}`, `tools/{conversation,files}`, plus tests; device: Drift schema/DAOs, `application/sync/{message_history_sync,attachment_fetch_service,resource_sync_bootstrap}`, `data/repositories/message_repository_impl`, `domain/models/message/audio_attachment`, chat screen). Below are the gaps grouped by severity.

You're following the workspace rule `no-backward-compatibility` — I did not flag missing migrations / wrappers.

---

### High severity (functional correctness or design contract violated)

1. [done] **Live inbound user audio still bypasses `message_attachments`** — `MessageRepositoryImpl._handleInboundAudio` (`device_apps/lib/data/repositories/message_repository_impl.dart:302-361`) saves the audio via `AudioStorageService` and writes `local_path` into the message's `metadata` JSON, but never inserts a `MessageAttachmentsCompanion`. Doc §8.4 explicitly says the live event path must "upsert a `message_attachments` row with `fetch_status='ready'`" so live and history converge on the same cache. Today: when the same user audio later arrives via `messages.history`, the sync will create a `pending` attachment row (no `findReadyByBlobId` hit because no row exists), and the device will re-`files.get` bytes it already had. This breaks the §8.4 "live cached short-circuit" guarantee for inbound user audio. The TTS / `message.voiced` path was correctly extended; the inbound user-audio path was not.

2. [done]**Inbound live audio is stored under `messageId`, not `<blob_hex>`** — `_handleInboundAudio` calls `_audioStorage.saveBytes(messageId: id, …)`. Doc §8.3 + §15 say "Filename = `<blob_hex>.<ext>` so two messages sharing a blob share one file on disk." The fetch service correctly uses the blob hex (`AttachmentFetchService._storageIdForBlob`), but the live path doesn't, producing duplicate copies on disk for the same blob. Same fix as item 1 — route live audio through the attachment table and `<blob_hex>` filename.

3. [done] **`fetcher.tick()` only runs once per history-sync trigger; failures never auto-retry** — `refreshMessageHistory` in `resource_sync_bootstrap.dart:127-132` builds a fresh `AttachmentFetchService` and ticks once. There is no periodic ticker, no queue subscription, no retry scheduler. The DAO has retry-aware `getFetchCandidates` (good), but nobody calls it again until the next history-sync trigger fires. A `pending` blob created by a live event (after the §8.4 fix) or a `failed` blob whose retry window opened would sit untouched until the user reconnects or pulls. Doc §8.2.b implies a continuously running loop with bounded concurrency.

4. [done] **Bounded-concurrency requirement (§8.2.b "2 in-flight blobs") is not implemented** — `AttachmentFetchService.tick()` (`attachment_fetch_service.dart:48-52`) iterates unique blobs **sequentially** with `await`. Effective in-flight = 1, never 2. Either rewrite to use a small worker pool or document that concurrency=1 is intentional and update §8.2.b.

5. [done] **`messages.history` log line missing severity emoji + uses `fineinfo`** — Doc §11 lists this as an INFO line ("⬇️ Resource served — request:messages.history"). Current `request_methods.py:75-82` uses `log.fineinfo(...)` with no emoji prefix, while sibling lines (`files.head`, `files.get`) correctly use `log.info("⬇️ …")`. Either drop to fineinfo for both, or promote `messages.history` to info with the emoji to match the doc and the rest of the file. Pick one and apply it consistently.

6. [done] **`files.get` log is missing the required `kind` extra** — Doc §11 says: *"add `kind` ∈ `{"character_photo","message_attachment"}` resolved by the resolver"*. Current `handle_files_get` (`request_methods.py:165-170`) logs `blob_id`, `size`, `chunk_count` only. `resolve_blob_id` already knows whether the hit came from `find_by_blob_id` (attachment) or the photo-scan fallback — surface that.

7. [done] **Missing `FILES_RESOLVER` logger / "Reference unresolved" log** — Doc §11 adds a new `FILES_RESOLVER` logger emitting `⚠️ Reference unresolved — {kind}:{id}` with `reason` ∈ `{"unknown_kind","not_found","unauthorized"}`. `domain/files_resolver.py` has no logger and just raises `ValueError` / `FileNotFoundError`. Add the logger + the four warning paths (the `unauthorized` case will be a no-op until item 8 is decided).

8. [done] **`resolve_ref` has no authz check** — Doc §7 step 4 says: *"authorize the device against the channel that owns the message (same authz model used elsewhere)"*. Current `resolve_ref` (`files_resolver.py:33-54`) reads `(message_pk, slot_index)` and returns the path without consulting the device id or the owning channel. Today there is no per-channel authz layer ("same authz model used elsewhere" doesn't actually exist in `request_methods.py`), so this is consistent with the rest of the data plane — but the doc commits to it. Either implement it or amend §7 step 4 to defer authz with a TODO so the doc and code agree.

---

### Medium severity (deviations from doc that don't break the loop today)

9. [done] **`refreshMessageHistory` re-syncs every server-backed channel; no per-channel chat-open trigger and no TTL** — Doc §8.2 trigger table lists *"Chat screen opens → if `now - channel.last_history_synced_at > STALE_TTL` (default 60 s), run incremental sync"* (also called out in §15: "Stale TTL for chat-open re-pull: 60 seconds"). Current `chat_screen.dart:35-40` calls `revalidateResourcesIfStale(['channels','policy','messages'])` which uses the **30-second** default in `gateway_notifier.dart:230` and triggers `refreshMessageHistory` for **all** channels, not just the opened one. Two deviations: (a) wrong TTL constant, (b) no per-channel selectivity. Either tune the default or pass `maxStale: const Duration(seconds: 60)` and add a per-channel sync entry point.

10. [done] **No pull-to-refresh in chat UI** — Doc §8.2 trigger table includes pull-to-refresh; `features/chat/` has no `RefreshIndicator` / `onRefresh`. Either add it or strike from the doc.

11. [done] **Two new device logs are missing / wrong-level**:
    - `'⬇️ Voice reply — {channelId} · live cached'` (INFO) — current `_handleEvent` logs `_log.debug('Message voiced', …)` (`message_repository_impl.dart:285`). Wrong level and wrong shape.
    - `'⬇️ History sync — {channelId} · pull_after'` start-of-sync line — `MessageHistorySync.syncChannel` only logs the result, not the start (`message_history_sync.dart:118`). Doc §11 lists both.
    - `'⬇️ Attachment fetch — queued · audio'` enqueue log with `dedup_count` is also absent.
    All current device logs use plain English (`'Attachment fetch ready'`) instead of the human-first `✅ {action} — {peer} · {kind}` shape required by the workspace rule and §11.

12. [done] **`MessageHistorySync` writes a JSON-encoded `voice` blob into `messages.metadata`** — `message_history_sync.dart:163-168` and `_audioMetadataMap` reproduce the legacy `metadata.voice` JSON shape. The whole point of moving to `message_attachments` (§4, §8.4 step 3, §13 step 4) is to stop writing audio metadata into `messages.metadata`. `MessageRepositoryImpl._parseTextContent` even falls back to that JSON if the attachment row is missing (`message_repository_impl.dart:504-512`) — leaving two parallel sources of truth. Drop the `voice` JSON write in the history sync; let the attachment row drive the UI exclusively.

13. [done] **`AttachmentFetchService` does not sha-verify locally** — Doc §8.2.b step 2 says *"verify `sha256(bytes) == blob_id` before publishing"*. The verification is currently delegated to `GatewayRequestClient.handleFileGetJsonResponse` (`gateway_request_client.dart:237-251`), which is fine in practice — but the design language ("before publishing `local_path`") sits in the fetch service and the test in §14 ("a tampered blob is rejected and marked `fetch_status='failed'`") would not exercise the fetch service in isolation today. Either add a defensive check in `_fetchOne` (cheap), or amend §8.2.b/§14 to point at the gateway client as the single verifier.

14. [done] **`AttachmentFetchService._storageIdForBlob` strips only `sha256:`; `AudioStorageService.saveBytes` then chooses extension by mime** — fine on mobile, but on web you get `data:audio/mpeg;base64,…` written into `local_path`. Doc §8.3 says web "data: URL" is OK and survives via Drift/IndexedDB — that part holds. Just verify the `MessageRepositoryImpl._audioAttachmentFromRecord` consumers play `data:` URLs (audio_player web side) — I didn't trace that path. Worth a quick spot-check before closing.

15. [done] **`MessageHistoryTool` docstring wasn't updated to mention the new normalized contract** — Doc §10 row 1 says *"Update its docstring and result dataclass type hints accordingly."* The docstring on `MessageHistoryTool` (`tools/conversation.py:223-225`) still talks about row limits but never says "normalized message dicts with `id` = external_id and `content[]` array". Minor but explicit in §10.

16. [done] **`AttachmentFetchService` carries unused `failedRetryDelay` / `fetchingTimeout` parameters from caller** — `refreshMessageHistory` constructs the service with defaults only; the doc-prescribed retry policy of "bounded exponential-backoff" (§8.2.b step 3) is reduced to a fixed 30-second window. Either implement exponential backoff or amend §8.2.b to "fixed 30 s retry, no backoff".

---

### Low severity (cosmetic / documentation drift)

17. [done] **Admin frontend `ChatMessageRow` type is stale** — `admin_frontend/src/lib/api/chat-channels.ts:19-31` still declares `media_path: string | null`, integer `id`, `external_id`, etc. Since `chat_channels/service.list_messages_all` returns raw rows from `_sync_list` (dropped `media_path` column), the field is permanently `undefined`. Doc §10 row 4 explicitly calls out auditing this file. UI doesn't use it (only `body` is rendered), so it's purely a type-annotation cleanup. Note: the admin "messages all" endpoint deliberately returns raw rows (per `test_messages_all_uses_raw_rows_for_admin_ui`) — that's a conscious choice and OK; just refresh the TS type.

18. [done] **`tts_debug` directory lifecycle** — confirmed no code writes to it anymore (only docs reference it). Workspace cleanup note: existing workspaces will retain a stale `tts_debug/` folder. Per §14 device test list and your workspace-reset policy this is fine; just worth mentioning in the "reflecting build updates" callout below.

19. [done] **No `MessageAttachmentListTool`** — Doc §10 lists this as optional ("Skip on first pass; add only if a real CLI workflow needs it"). Skipping is consistent with the doc.

20. [done] **`message-history.mdx` mintdocs page** — Doc §12 says it is optional. Skipping is fine; just decide explicitly.

21. [done] **§9 wording vs implementation** — Doc §9.1 says new `message.voiced` fields are "additive — older devices ignore unknown fields". Today, every device that gets a `message.voiced` is post-change (no compat shim, per workspace rule), so the wording is misleading rather than wrong. Consider updating §9.1 to drop the "additive" framing.

---

### Things that match the doc exactly and look good

- `message_attachments` DDL + indexes match §4 verbatim, including `UNIQUE(message_pk, slot_index)`, the two indexes, and the field set.
- `messages.media_path` column dropped from `_DDL`; no `update_media_path` callers remain (verified by grep).
- `persist_inbound` creates exactly one attachment row per audio item, with `metadata = {"source":"user_audio", "transcript":…}` (§5.1 verified by `test_persist_inbound_audio_creates_attachment_row`).
- `_synthesize_and_send` saves to `data/media/<channel_id>/<reply_pk>.<ext>`, inserts an attachment with `source=character_tts` + `reply_to_message_id` + `model` + `voice`, and emits `message.voiced` with `blob_id`/`ref`/`size`/`chunk_size`/`chunk_count` (§5.2 + §9.1 verified by `test_synthesize_and_send_stores_tts_attachment`).
- TTS-failure semantics: no attachment row created, agent text reply persists (§5.2 last paragraph) — verified by the structure of the try/except in `_synthesize_and_send`.
- `messages.history` returns the §6 contract (`id` = external id, `content[]` with text + audio, blob metadata in `metadata`, no inline `audio` bytes, no `media_path`) — verified by `test_message_history_returns_audio_metadata_without_bytes`.
- `_sync_history` page-aggregates attachments in **one** query (`WHERE message_pk IN (…)`) — good, avoids N+1.
- `resolve_ref('message_attachment:…')` uses `rsplit(':', 1)` so message ids may contain colons (§7) — verified by `test_message_attachment_ref_and_blob_id_resolve_to_saved_audio` using `msg:resolver:audio`.
- `resolve_blob_id` does indexed attachment lookup first, falls back to character-photo scan (§7) — verified by the test asserting both paths.
- `MessageHistorySync` is incremental, idempotent, dedups on `findReadyByBlobId` (§8.2.a) — verified by `syncChannel reuses a ready local path for duplicate blobs`.
- `AttachmentFetchService` dedups by `blob_id`, marks all sharing rows ready in one update (§8.2.b dedup) — verified by `tick fetches each blob once and marks all matching rows ready`.
- `last_history_synced_at` advances and is sent as `after` on the next pull (§8.2.a step 5) — verified by `syncChannel sends last server timestamp as after cursor`.
- `MessageAttachmentsDao` exposes the §8.1 surface (`watchForMessage`, `findByBlobId`, `markFetching/Ready/Failed`, plus `getFetchCandidates` for retry).
- `message.voiced` event upserts a `ready` attachment via `_attachmentsDao.insertOrUpdate` (§8.4 step 3 for TTS replies) — verified by `message.voiced event upserts a ready attachment row`.
- `AudioAttachment` extended with `blobId`, `remoteRef`, `size`, `chunkSize`, `chunkCount`, `fetchStatus`, and `isPlayable` is the §8.5 derived getter.
- `chunk_count_for_size` and `DEFAULT_CHUNK_SIZE` are imported from `domain/blob_store`, so history's chunk math matches `files.head` exactly (§6 field note).

---

### Recommended priority order to close the gaps

1. Fix items **1 + 2** together (route live inbound audio through `message_attachments` + filename = blob hex). One PR.
2. Fix item **12** (drop the `voice` JSON write in history sync) — small, removes parallel-source bug.
3. Fix items **5, 6, 7, 11** (logging consistency) — single sweep.
4. Fix items **3 + 4** (continuous tick + bounded concurrency) — affects reliability.
5. Decide on **8** (authz) and **9 + 10** (chat-open TTL / per-channel / pull-to-refresh): either implement or amend the doc.
6. Cleanups: **15, 16, 17, 18, 21**.

---

### Per workspace rules

- Per `no-backward-compatibility.mdc`: this review assumes initial-development mode. I did not flag any migration-shaped gaps; I treated dropped columns and replaced wire shapes as the intended end state.
- Per `Document-Executed-Plans.mdc`: §12 mintdocs touches (architecture pages for `protocol-contract.mdx`, `unified-message.mdx`, `communication-manager.mdx`, `agent-manager.mdx`, `architecture-overview.mdx`) are still pending — the `hiro-docs` repo's `protocol-contract.mdx` and `unified-message.mdx` are dirty in your status, so docs are mid-flight; just confirming they are tracked.
- Per `consider-creating-tools-first.mdc` (cursor rule attached to `domain/message_attachments.py`): no exposed CLI/Tool/HTTP/Admin surface for listing or inspecting message attachments was added — consistent with §10's decision to skip `MessageAttachmentListTool` on first pass. Mentioning so you can confirm it's intentional.

### Reflecting build updates (per workspace rule)

To pick up this branch cleanly:

1. **Reset existing workspaces** before testing — `messages.media_path` is dropped, the `message_attachments` table is added, and `messages.history` wire shape changed. Per the doc §intro: delete `<workspace>/data/data.db` and `<workspace>/data/media/` (and any leftover `<workspace>/data/tts_debug/` directory).
2. **Bump device Drift schema and wipe the device DB** — `AppDatabase.schemaVersion` is now 6 and `onUpgrade` does a destructive recreate, so existing installs lose local message history on first launch (intentional).
3. **Regenerate Drift / Freezed code** if you haven't already after the schema changes: `dart run build_runner build --delete-conflicting-outputs` in `device_apps/`.
4. No new dev tools or env vars introduced; `mintdocs/build/first-time-setup.mdx` does not need updating (matches §12's note "No tooling change — skip").
