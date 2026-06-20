# Cross-Cutting Resilience

> SSE is genuinely **global and well-built** — preserve it. The gaps are **error handling**
> and **server-unavailable** handling, both currently **per-feature**, plus one duplicated
> banner. These are resilience fixes, **not** logging/telemetry (that's deferred — see
> [00-overview.md](00-overview.md) §5).

---

## 1. SSE / live updates — GLOBAL (preserve; two small fixes)

Only **2** `EventSource` constructions exist, both in shared per-tab singletons
(`live/status.svelte.ts:51`, `knowledge-event-stream.svelte.ts:90`). **eval rides the shared
stream** (`eval-events.ts` → `connectEvalEvents` subscribes onto `knowledgeEventStream`) — it
does *not* open its own. Tab-hidden pausing + per-origin connection-budget handling are
consistent across both. This is the model.

Two fixes:
- **Dedup the "degraded" banner.** The 9-line amber banner is byte-identical in
  `KnowledgePage.svelte:75` and `EvalPage.svelte:95` — and should just use the existing
  `InlineWarningAlert` (built for exactly this). Extract `<LiveDegradedBanner>` or pass the
  message through `InlineWarningAlert`.
- **`liveStatus.degraded`/`error` is computed but read by nobody** (grep: 0 consumers). Lift
  the knowledge stream's 8s grace-window `degraded` logic into a shared helper so `liveStatus`
  exposes it too, and render it (the header connection dot in `AdminShell.svelte:55` is the
  natural home).

## 2. Error handling — PER-FEATURE → add a global boundary

`apiRequest` throws on timeout/network/`!ok` (`client.ts:81`); every controller catches
independently into its own error string (inline `InlineDestructiveAlert` *or* toast, chosen
ad-hoc per feature). **No global boundary exists** — no `+error.svelte`, no
`hooks.client.ts`/`handleError`, no `window` `unhandledrejection` listener (all confirmed
absent). An uncaught throw (forgotten try/catch, throw in an `$effect`) **dies silently with
no recovery UI**.

Fix — minimal, structural:
```
src/hooks.client.ts      → export handleError = ({ error }) => ({ message: friendly(error) })
src/routes/+error.svelte → renders the recovery page (retry / back to dashboard)
```
That alone means new features stop being one-forgotten-catch away from a blank page. (No
external reporting — see deferred note.)

## 3. Server-unavailable / offline — PER-FEATURE (a real detector used in 1 place)

A shared detector exists — `server-readiness.svelte.ts` polls `/api/runtime/status` with
exponential backoff and exposes `serverReadiness` + `ServerStartingBanner` — **but it's wired
into exactly one consumer** (`ChatMessageComposer.svelte:7`). Every other feature fails
per-call: during a server restart, 10 open panels show 10 uncoordinated "request timed out"
errors with no "server is down" awareness. `apiRequest` is **one-shot — no retry/backoff
anywhere** except the readiness poller.

Fix:
- Lift `serverReadiness` (fed by `liveStatus.connected` + a 5xx/connection-refused signal
  from `apiRequest`) into the always-mounted `AdminShell` → **one** app-level "server
  unavailable" banner. Per-feature error blocks then defer to it ("server is down" vs "this
  call failed") instead of each shouting independently.

---

## Deferred (see [00-overview.md](00-overview.md) §5)

- **Frontend logging / telemetry** — a new feature; backend logging is good. The 8 existing
  `console.warn/error` swallow-and-log sites stay as-is. The error boundary above is
  resilience, not logging — keep them mentally separate.

## Ranked by how much the gap hurts scaling

1. **Error boundary (§2)** — every new feature otherwise hand-rolls catch-and-surface; a miss = silent dead page. Structural.
2. **Server-unavailable (§3)** — cheap fix (lift to shell), worsens with each panel added.
3. **SSE fixes (§1)** — cosmetic; the system is already correct.
