I have enough material. Here's the prioritized review.

---

# Code review — admin chat live updates

## Severe

### 1. `ChatMessageAttachmentAudio.svelte` — load runs only **once** in `onMount`; inline updates won't refresh the audio

The merge replaces the `ChatHistoryMessage` row in place, and the `{#each}` is keyed by `message.id`, so the same `ChatMessageAttachmentAudio` instance lives across the optimistic→server transition. But the blob fetch is in *`onMount`** — it fires exactly once, against the **first** `audioItem.body` it ever saw.

Concretely: an optimistic audio bubble has `body = "optimistic_audio:<id>"` and uses `optimistic_audio_url`. When the resync replaces that row with the real one `body = "message_attachment:<id>:0"`, no `optimistic_audio_url`), the component **does not refetch** — `audioUrl` stays pointed at the now‑revoked / about‑to‑be‑revoked object URL of the optimistic blob. After the optimistic cleanup runs (it won't, because `onMount`'s teardown only fires at unmount), the user sees the old optimistic audio forever, or a broken `<audio>` after the URL is revoked.

The component needs an `$effect` keyed on `audioItem.body` (and the optimistic flag) that refetches/swaps when the `body` reference changes, with proper teardown of the previous object URL. The current `onMount` design is incompatible with the live-update goal.

This is the highest-impact bug because the headline use case ("TTS/transcript fills in for the last message") will visibly fail for audio.

---

### 2. `currentPollIntervalMs()` is read at start time but never re-applied to a running timer

`startPolling` calls `setInterval(…, currentPollIntervalMs())`. After backoff increases `pollErrorStreak`, only `restartPollingTimer()` rebuilds the timer with the new interval — and that's only called from the **error** branches. After successful recovery, `resetPollErrors()` does call `restartPollingTimer()` only `if (hadBackoff)` — that part is correct.

The actual bug: in `pollMessagesOnce`, when `pollErrorStreak += 1` happens **and then** `restartPollingTimer()` runs, the function uses *`stopPolling(); pollTimer = setInterval(...)`**. Fine. But `restartPollingTimer` doesn't check `pollTickInFlight === false` (the failing tick is still in its `finally`), and `stopPolling` clears the timer mid-tick. The next interval fires `currentPollIntervalMs()` worth later — **using the streak value at the moment `restartPollingTimer` ran**, which is correct only because `currentPollIntervalMs` is called inside `setInterval(...)`'s arg. That part works.

What does **not** work: `setInterval` callbacks are scheduled at the **fixed** interval captured at creation time. If a later success calls `resetPollErrors → restartPollingTimer`, the new timer is created **inside `pollMessagesOnce`'s `finally` chain**, while the old timer was already fired-and-cleared. That's also fine.

But: `restartPollingTimer()` calls `stopPolling()` which sets `syncing = false`, even when the very tick that just incremented the streak hasn't returned from its `finally`. The `finally` then runs `syncing = false` again — harmless — but `pollTickInFlight` is still `true` until that `finally`. Net effect: a brief window where another `restartPollingTimer` (e.g. from the Refresh button via `resetPollErrors`) could `setInterval` while the in-flight tick keeps running. Not a corruption bug, but worth tightening: `restartPollingTimer` should be the only thing that touches the timer, and it should not touch `syncing`.

**Real concrete severe issue here:** `resetPollErrors()` is called inside `pollMessagesOnce` **before** the `finally` clears `pollTickInFlight`. If `restartPollingTimer` synchronously schedules a new `setInterval`, and the user has the dev tools throttled, the next tick could attempt to start while `pollTickInFlight` is still `true`. The guard at the top of `pollMessagesOnce` saves it `if (pollTickInFlight) return`), so it's defensive — but the design relies on that guard. **Document or restructure** so the timer reset happens after the `finally`. Today it's correct only by virtue of the in-flight guard; that's fragile.

---

### 3. Optimistic message dedup against server reply is broken when external id matches

The merge function does dedup external→pk transitions: when a row arrives whose `id` (external) was previously associated with a **different** `message_pk`, it deletes the old `message_pk` from the map. Good.

Problem: the optimistic row uses `id: sent.data.message_id` (the **real** server-assigned external id from the `message_send` response) and `message_pk: -1` (negative sentinel). When the by‑pk resync later returns the real row with the same `id` but `message_pk = 42`:

- `pkByExternalId.get("real-id")` → `-1` (the optimistic pk)

- `previousPk !== message.message_pk` → `-1 !== 42` ✓

- `byPk.delete(-1)` — drops the optimistic entry

- `byPk.set(42, real)` — sets the real one

That part works. But the *`{#each}` is keyed by `message.id` (external id)**, not `message_pk`. Both rows share the same external id, so Svelte sees this as **one stable key** and reuses the DOM node — which is what you want for text. For audio, this is exactly bug **#1**: the component doesn't see `audioItem` change is meaningful and never refetches.

Also: between the moment the user records audio and the moment the server's `message_send` returns, the optimistic insert uses the response's `message_id` — so there is no window where two rows with the same external id coexist. Fine. **But:** what if `sendChatMessage` succeeds and a tail poll lands **before** `addOptimisticMessage` runs (very tight, but possible since the network call awaits)? The tail returns the real row, merge inserts it under `byPk = real_pk`, then `addOptimisticMessage` inserts the optimistic with `pk = -1` and the same external id. Now `pkByExternalId` is updated to `-1` for that external id. The next merge sees an incoming with the real pk, finds `previousPk = -1`, deletes the optimistic — OK, but until that happens the real row sits in `byPk[real_pk]` while the optimistic sits in `byPk[-1]`, both with the same external id. **Sort by `(created_at, id)`** treats them as equal, two rows render with the same key, **Svelte will warn / behave unpredictably**.

Mitigation is simple: at the start of `addOptimisticMessage`, if a row with the same external id already exists in `messages` with a positive `message_pk`, **skip** the optimistic insert. The current code doesn't.

---

## High

### 4. `pollMessagesOnce` does **two** sequential awaits without re-checking the eligibility gate between them

After the tail call returns, the code merges, then awaits the resync call. Between those, the user may have switched tabs `activeTab → 'channels'`), the document may have hidden, or the messages section may have unmounted. The `selectedChannelId` check guards channel changes (good), but not the other gates. Result: a hidden tab / unmounted panel can still drive the merge of resync results into `$state` and fire one extra render after the user has left.

Cheap fix: before the second `await`, also check `liveUpdatesEligible`. Before each `messages = …` assignment, re-check `selectedChannelId !== rawChannelId` **and** `liveUpdatesEligible`.

---

### 5. `messages` and `tailCursor` get cleared in **four** different places — easy to drift

Search for `messages = []; tailCursor = null;`: it appears in `ensureSelectedChannel`, `loadChannels` (when selection becomes invalid), `loadMessages` (when no channel), `openMessages`, `submitDelete`, and the `selectedChannelId` setter. That's six. They are not all in agreement (e.g. the setter does it before the assignment; `loadMessages` does it before the fetch). One forgotten site = stale messages from a previous channel briefly visible. Centralize in one helper, e.g. `resetMessageState()`, and call it from each of those.

---

### 6. Tail call uses `TAIL_LIMIT = 50` but never paginates

If the server has > 50 new messages since the last cursor (e.g. tab was hidden 30+ minutes during a busy chat), one tail call returns 50 rows, merges, advances the cursor — and the **next** poll, one second later, fetches the next 50. Correct, but slow to catch up. Acceptable for v1; mention it as a known characteristic in the docs/PR. Not a bug, but worth noting since the design spec said "tail" was the cheap fast path.

A bigger concern: when **empty tab**/load happens for an empty channel, `cursorFromMessages` returns `null` and the code path at lines 232–254 issues a **full** `listChatMessages(channelId)` (no params). On a channel with 50,000 messages, that's the entire history every time the cursor is null. The only path leading here is "channel had only optimistic messages and no real ones." Edge case, but worth a guard: only trigger the full re-load if `messages` actually has at least one optimistic and zero positive-pk rows (current code does check `messages.some(m => m.message_pk < 0)` — good — so this is fine, not a bug). Disregard, on re-read this guard is correct.

---

## Medium

### 7. `restartPollingTimer` doesn't run an immediate tick, but `startPolling` does

`startPolling` does `void pollMessagesOnce()` immediately, then sets the interval. `restartPollingTimer` skips the immediate tick. So when `resetPollErrors` triggers `restartPollingTimer`, the user waits a full `POLL_INTERVAL_MS` for the next data refresh, even though we just recovered from backoff. Either run an immediate tick in `restartPollingTimer` or document the intent.

### 8. `_sync_history_by_pks` raises `ValueError` for too-many pks; the route handler does not catch it

`_MAX_MESSAGE_PK_RESYNC = 16`. If the client somehow sends 17 (hand-crafted request, future bug), `_sync_history_by_pks` raises `ValueError` from inside `run_in_threadpool`, which becomes a 500 with whatever the global handler emits. Better: validate count at the route level (you already do other validation there) and return 400. Also: there's no upper bound check on the route — clients could send arbitrarily long `?message_pk=…&message_pk=…` lists; the only thing protecting the server is the service-layer raise. Move the cap to the route handler with `len(message_pk) > 16 → 400`, and let the service trust its input.

### 9. Sort uses `localeCompare` on `created_at` and `external_id`

`a.created_at.localeCompare(b.created_at)` works for ISO‑8601 because lexical = chronological, but it is **locale-aware** and could give surprising results in environments with unusual collations (Turkish 'I' etc., though digits and `TZ-:` aren't affected). For ISO timestamps and UUID-ish ids, you want a plain string compare: `a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0`. Tiny but the server uses byte-wise SQL comparison; aligning the client avoids one more "shouldn't happen" class.

### 10. Test coverage is thin for the new client-side merge logic

`chat-channel-message-merge.ts` is a pure module — perfect for unit tests, especially the optimistic→real transition (bug #3) and the tie-break path. There are zero tests for it. Server has good new tests; client has none.

### 11. `apiRequest` assumes the URL constructed in `listChatMessages` is OK with repeated `message_pk` keys

`URLSearchParams.append('message_pk', …)` produces `?message_pk=1&message_pk=2`. FastAPI with `Query(default=None)` and type `list[int] | None` accepts that. Confirmed working. But there's no test that the route round-trips a multi-pk request correctly — only service-level test mocks `_sync_history_by_pks`. Add a route test (or a smoke test) that exercises the actual query parsing.

---

## Low

### 12. `optimisticMessagePk = -1` then `optimisticMessagePk--` will eventually underflow

Cosmetic — would take billions of voice messages. Fine.

### 13. Hard-coded strings: `'admin'` for sender_id, `'user'` for sender_type in optimistic messages

Magic strings repeated in two places `submitDraftText`, `finalizeRecording`). Lift to local constants.

### 14. `liveUpdatesPaused` banner copy

`"Live updates paused - retrying"` uses an ASCII hyphen with single spaces; design used em‑dash style elsewhere. Minor consistency.

### 15. `cursorFromMessages` skips negative `message_pk` rows — but the comment doesn't say why

Drop a one-line comment that this is to ignore optimistic rows so the tail cursor doesn't get poisoned by a fake ISO timestamp newer than the latest real row.

---

## TL;DR (severity, top to bottom)

1. *`ChatMessageAttachmentAudio` only loads on mount** — defeats the resync goal for audio; needs an `$effect` on `audioItem.body`.

2. *`pollErrorStreak` / `restartPollingTimer` ordering** is correct only by virtue of the in-flight guard; restructure so timer reset happens after `finally`.

3. **Optimistic + real-row coexistence window** can produce two rows with the same `{#each}` key; guard `addOptimisticMessage` against an existing real row.

4. **Eligibility re-check** missing between the tail and resync awaits.

5. *`messages = []; tailCursor = null;`** scattered across 6 sites — centralize.

6. Server pk cap should be enforced at the **route**, not the service.

7. Sort with byte-wise compare, not `localeCompare`.

8. **No client-side tests** for `mergeChatHistoryMessages` — easy wins for the most subtle logic in this PR.

The server-side extension and the controller architecture are clean. The two real correctness bugs are **#1 (audio refresh)** and **#3 (optimistic dedup)** — both directly undermine the user-facing promise of this work.