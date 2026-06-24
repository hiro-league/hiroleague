/**
 * Cross-page server-readiness state.
 *
 * The admin UI binds its port very early in HiroServer startup (right after
 * the workspace DBs exist), well before the main HiroServer HTTP listener is
 * up. Features that depend on the main HTTP listener — today, chat send via
 * ``post_invoke_sync`` — surface a banner + disable their actions while the
 * server is still starting.
 *
 * The store polls ``GET /api/runtime/status`` on a short cadence until the
 * server reports ``ready: true``, then stops polling. It restarts polling on
 * demand if a consumer calls ``markStale()`` (e.g. after a restart action).
 *
 * A single shared instance is exposed so multiple panels can read the same
 * state without each maintaining its own poller.
 */

import { getRuntimeStatus, type RuntimeStatus } from '$lib/api/runtime';
import { registerServerStaleHandler } from './server-stale-signal';

const POLL_INTERVAL_MS = 1000;
const POLL_INTERVAL_MAX_MS = 4000;

export type ServerReadinessStore = ReturnType<typeof createServerReadinessStore>;

function createServerReadinessStore() {
  let ready = $state(false);
  /** True once the main HTTP listener has reported ready at least once this session. */
  let everReady = $state(false);
  let status = $state<RuntimeStatus | null>(null);
  let lastError = $state<string | null>(null);
  let polling = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let backoffMs = POLL_INTERVAL_MS;
  let stopped = false;

  function clearTimer() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }

  async function pollOnce() {
    try {
      const payload = await getRuntimeStatus();
      status = payload.data;
      ready = Boolean(payload.data.ready);
      lastError = null;
      if (ready) {
        everReady = true;
        backoffMs = POLL_INTERVAL_MS;
      }
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
      ready = false;
      backoffMs = Math.min(backoffMs * 2, POLL_INTERVAL_MAX_MS);
    }
  }

  function schedule(delay: number) {
    clearTimer();
    if (stopped) return;
    timer = setTimeout(() => {
      void tick();
    }, delay);
  }

  async function tick() {
    polling = true;
    try {
      await pollOnce();
    } finally {
      polling = false;
    }
    if (ready || stopped) {
      clearTimer();
      return;
    }
    schedule(backoffMs);
  }

  /** Subscribe and start polling if not already ready. Idempotent. */
  function subscribe(): () => void {
    stopped = false;
    if (!ready && timer === null && !polling) {
      void tick();
    }
    return () => {
      // Unsubscribers are idempotent; the shared instance keeps running until
      // the page unloads or ``markStale()`` is called and ready flips back.
    };
  }

  /**
   * Force a fresh poll cycle. Used after actions that may take the server
   * temporarily offline (e.g. restart). Resets backoff so we recover fast.
   */
  function markStale() {
    ready = false;
    backoffMs = POLL_INTERVAL_MS;
    stopped = false;
    schedule(0);
  }

  /** Stop all polling. Mostly useful for tests. */
  function dispose() {
    stopped = true;
    clearTimer();
  }

  registerServerStaleHandler(markStale);

  return {
    get ready() {
      return ready;
    },
    get everReady() {
      return everReady;
    },
    get status() {
      return status;
    },
    get lastError() {
      return lastError;
    },
    get polling() {
      return polling;
    },
    subscribe,
    markStale,
    dispose
  };
}

/** Shared singleton — every consumer sees the same readiness state. */
export const serverReadiness: ServerReadinessStore = createServerReadinessStore();
