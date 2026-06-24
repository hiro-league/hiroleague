# Cross-Cutting Resilience

> SSE is genuinely **global and well-built** — preserve it. The gaps are **error handling**
> and **server-unavailable** handling, both currently **per-feature**, plus one duplicated
> banner. These are resilience fixes, **not** logging/telemetry (that's deferred — see
> [00-overview.md](00-overview.md) §5).

> **Working rules for the implementer**
> - We are in **initial-development mode**: no backward-compat, no migrations, no wrappers
>   (see `.claude/rules/no-backward-compatibility.md`). Refactor in place; delete the old code.
> - Admin UI lives in `admin_frontend/`. All paths below are relative to that folder unless
>   noted. Verify with `npm run check` and `npm run test:unit` from `admin_frontend/`.
> - Line numbers are anchors that may drift — **grep for the named symbol** rather than
>   trusting the number.
> - Follow Svelte 5 conventions (runes, `$state`/`$derived`, scoped styles). The
>   `svelte-best-practice` skill is the reference.

The three sections are **independent** — each can ship as its own PR. Suggested order is the
"Ranked" list at the bottom (§2 → §3 → §1).

---

## 1. SSE / live updates — GLOBAL (preserve; two small fixes)

Only **2** `EventSource` constructions exist, both in shared per-tab singletons
(`src/lib/live/status.svelte.ts:51`, `src/lib/features/knowledge/shared/knowledge-event-stream.svelte.ts:90`).
**eval rides the shared stream** (`src/lib/features/eval/shared/eval-events.ts` →
`connectEvalEvents` subscribes onto `knowledgeEventStream`) — it does *not* open its own.
Tab-hidden pausing + per-origin connection-budget handling are consistent across both. This is
the model. **Do not add a third `EventSource`.**

### Fix 1a — Dedup the "degraded" banner

The amber banner is **byte-identical** in two files and should use the existing
`InlineWarningAlert` (built for exactly this):
- `src/lib/features/knowledge/KnowledgePage.svelte:75-83`
- `src/lib/features/eval/EvalPage.svelte:95-103`

Both render the same markup and read `knowledgeEventStream.degraded`. `InlineWarningAlert`
(`src/lib/ui/InlineWarningAlert.svelte`) takes props `{ message: string; title?: string; class?: string }`.

**Steps**
1. Create `src/lib/live/LiveDegradedBanner.svelte` — a thin wrapper that reads
   `knowledgeEventStream.degraded` and renders `InlineWarningAlert` with the existing copy:
   > "Live updates are disconnected — the browser may be out of connections. Close some other
   > Hiro Admin browser tabs and they'll resume automatically."
   Guard the render with `{#if knowledgeEventStream.degraded}` inside the component (so callers
   just drop `<LiveDegradedBanner />` with no condition). Keep the `mb-3` spacing via the
   `class` prop.
2. Replace the inline `{#if knowledgeEventStream.degraded}…{/if}` block in **both** pages with
   `<LiveDegradedBanner />` and remove the now-unused `knowledgeEventStream` import if nothing
   else in the page uses it (EvalPage imports it at `:10`, KnowledgePage at `:15` — check first).

**Acceptance**
- The two pages no longer contain the literal amber `<div role="status" …>` block.
- `LiveDegradedBanner` renders nothing when `knowledgeEventStream.degraded` is `false`.
- `npm run check` passes.

### Fix 1b — Surface `degraded` in the always-visible header dot

> ⚠️ **Correction to the earlier draft of this doc:** `liveStatus` does **not** have a
> `degraded` field. It exposes `connected` and `error` getters (`status.svelte.ts:95-100`),
> and grep confirms **0 consumers of either**. The 8s grace-window `degraded` logic lives
> **only** in the knowledge stream (`knowledge-event-stream.svelte.ts`: `DEGRADE_GRACE_MS = 8000`
> at `:31`, set at `:107`, exposed via getter at `:175`). So this is "lift + expose", not
> "wire up an existing field".

Today the header connection dot in `AdminShell.svelte` (rendered at `:238-242`, driven by the
`headerStatus` derived at `:55`) reflects only `workspace_status` from the status payload — it
goes **green/amber/red** but never reflects a dead live-events stream. A user with a frozen SSE
connection sees a green dot.

**Steps**
1. Extract the grace-window degraded detector from `knowledge-event-stream.svelte.ts` into a
   small shared helper (e.g. `src/lib/live/degraded.svelte.ts`) that both the knowledge stream
   and `liveStatus` can use: it watches a `connected` boolean and flips `degraded = true` after
   `DEGRADE_GRACE_MS` of continuous disconnect, resetting on reconnect.
2. Have `createLiveStatusStore()` in `status.svelte.ts` use the helper (feed it the existing
   `connected` state) and add a `degraded` getter to its returned object.
3. In `AdminShell.svelte`, when `liveStatus.degraded` (or the knowledge stream's) is true, tint
   the header dot and update its `title`/`aria-label` to say live updates are disconnected. Keep
   the existing `statusDotClass` workspace colors as the base; degraded is an overlay state.

**Acceptance**
- Killing the SSE stream (e.g. stop the server, or open ~3 tabs to exhaust the connection
  budget) flips the header dot to a degraded appearance within ~8s, with an explanatory tooltip.
- The knowledge stream still drives `LiveDegradedBanner` (no regression to Fix 1a).
- `npm run check` passes.

> This fix is **cosmetic / nice-to-have** (see ranking). If time-boxed, ship Fix 1a alone.

---

## 2. Error handling — PER-FEATURE → add a global boundary

`apiRequest` throws on timeout/network/`!ok` (`src/lib/api/client.ts` — network throw at `:71`,
parse at `:78`, `!ok` at `:82`); every controller catches independently into its own error
string (inline `InlineDestructiveAlert` *or* toast, chosen ad-hoc per feature). **No global
boundary exists** — no `+error.svelte`, no `hooks.client.ts`/`handleError`, no `window`
`unhandledrejection` listener (all confirmed absent). An uncaught throw (forgotten try/catch,
throw in an `$effect`) **dies silently with no recovery UI**.

This is a SvelteKit app, so use the framework's two built-in hooks:

```
src/hooks.client.ts      → export const handleError = ({ error }) => ({ message: friendly(error) })
src/routes/+error.svelte → renders the recovery page (retry / back to dashboard)
```

**Steps**
1. Create `src/hooks.client.ts` exporting `handleError` (SvelteKit's client error hook). Map the
   thrown `Error` to a friendly `{ message }`. Do **not** add external reporting (see deferred
   note) — just produce a readable message. Keep `console.error` here is fine for local dev.
2. Create `src/routes/+error.svelte`. Read `$page.error.message` and `$page.status`, render a
   recovery UI with a "Retry" (reload / `invalidateAll`) and a "Back to dashboard" link
   (`${base}/`). Reuse existing UI primitives (`Button`, `InlineDestructiveAlert`) for visual
   consistency.
3. (Optional, recommended) Add a `window.addEventListener('unhandledrejection', …)` in
   `hooks.client.ts` to surface promise rejections that escape `apiRequest` callers — route them
   through the same friendly message / a toast rather than letting them vanish.

**Acceptance**
- A deliberately thrown error in a route load or component (temporary test throw) renders
  `+error.svelte`, not a blank page.
- New features no longer need to hand-roll catch-and-surface to avoid a dead page.
- `npm run check` passes; no new external-reporting dependency added.

> **Why this is #1:** every new feature otherwise hand-rolls catch-and-surface; a single
> forgotten catch = a silent dead page. The boundary makes that failure mode structural, not
> per-developer-discipline.

---

## 3. Server-unavailable / offline — PER-FEATURE (a real detector used in 1 place)

A shared detector exists — `src/lib/runtime/server-readiness.svelte.ts` polls
`/api/runtime/status` with exponential backoff (`POLL_INTERVAL_MS = 1000` → `MAX = 4000`) and
exposes `serverReadiness` + `ServerStartingBanner` (`src/lib/runtime/ServerStartingBanner.svelte`)
— **but it's wired into exactly one consumer**: `ChatMessageComposer.svelte` (store import `:8`,
`<ServerStartingBanner />` at `:89`, `serverReadiness.ready` gating send at `:116/:130/:133`).
Every other feature fails per-call: during a server restart, 10 open panels show 10
uncoordinated "request timed out" errors with no "server is down" awareness. `apiRequest` is
**one-shot — no retry/backoff anywhere** except the readiness poller.

**Steps**
1. Mount `serverReadiness` once in the always-mounted shell. In `AdminShell.svelte`, call
   `serverReadiness.subscribe()` in the existing `onMount` (alongside `liveStatus.start(...)`),
   and render **one** app-level "server unavailable" banner near the header when
   `!serverReadiness.ready`. Reuse `ServerStartingBanner` or a sibling built on the same store.
2. Feed readiness from the signals we already have: `liveStatus.connected` going false, plus a
   5xx / connection-refused signal from `apiRequest`. The cleanest seam: when `apiRequest`
   throws a network error or sees a 5xx, call `serverReadiness.markStale()` so the shared poller
   re-checks immediately. (`markStale()` already exists at `server-readiness.svelte.ts:95`.)
3. Per-feature error blocks then **defer** to the shell banner: when `!serverReadiness.ready`,
   show "server is down, retrying…" instead of each feature shouting its own "request timed out".
   At minimum, suppress the redundant per-call error toasts while the shell banner is showing.

**Acceptance**
- Restarting the server shows **one** shell-level banner, not N per-panel timeout errors.
- The banner clears automatically when `/api/runtime/status` reports `ready: true` (poller stops
  on its own).
- `ChatMessageComposer`'s existing send-gating still works (no regression).
- `npm run check` passes.

---

## Deferred (see [00-overview.md](00-overview.md) §5)

- **Frontend logging / telemetry** — a new feature; backend logging is good. The 8 existing
  `console.warn/error` swallow-and-log sites (across `characters`, `eval`, `knowledge`
  controllers) stay as-is. The error boundary in §2 is resilience, not logging — keep them
  mentally separate. Do **not** route these through any new reporting pipe as part of this work.

## Ranked by how much the gap hurts scaling

1. **Error boundary (§2)** — every new feature otherwise hand-rolls catch-and-surface; a miss = silent dead page. Structural. **Do first.**
2. **Server-unavailable (§3)** — cheap fix (lift to shell), worsens with each panel added.
3. **SSE fixes (§1)** — cosmetic; the system is already correct. Fix 1a (dedup) is trivial; Fix 1b (header dot) is optional polish.
