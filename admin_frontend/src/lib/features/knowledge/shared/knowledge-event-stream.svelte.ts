/**
 * Shared, per-tab SSE multiplexer for `/api/knowledge/events`.
 *
 * WHY: the admin used to open a SEPARATE `EventSource` per feature (jobs, eval, graph) —
 * 3 long-lived connections to one origin, on top of the app-wide status stream. Browsers
 * cap HTTP/1.1 at ~6 connections per host, so a few open admin tabs + ordinary fetches
 * (e.g. opening logs) would starve the connection pool and unrelated requests would stall
 * until their client timeout fired ("signal is aborted without reason"). Random freezing
 * is not a clean design.
 *
 * FIX: ONE `EventSource` per browser tab. Features `subscribe(eventType, handler)`; this
 * module owns the single connection and fans each SSE frame out to the registered
 * handlers by `event.type`. The backend already forwards every knowledge event type on
 * this one stream, so nothing server-side changes. Net: a Knowledge tab now consumes one
 * knowledge connection, not three.
 *
 * The connection opens on the first subscriber and closes when the last one leaves
 * (ref-counted), and reopens if the selected workspace changes. `degraded` flips true when
 * the stream can't (re)establish within a grace window — the most likely cause is the
 * per-origin connection budget being exhausted (too many admin tabs) — so the UI can warn
 * the user instead of silently losing live updates.
 */
import { base } from '$app/paths';
import { PREF_KEYS } from '$lib/preferences/keys';

type Handler = (event: MessageEvent) => void;

const KNOWLEDGE_EVENTS_PATH = '/api/knowledge/events';
// Grace period before we call the stream "degraded": EventSource auto-reconnects on
// transient blips, so we only warn if it stays down past this window.
const DEGRADE_GRACE_MS = 8000;

function currentWorkspace(): string | null {
  return typeof localStorage === 'undefined'
    ? null
    : localStorage.getItem(PREF_KEYS.selectedWorkspace);
}

function createKnowledgeEventStream() {
  let source: EventSource | null = null;
  let workspace: string | null = null;
  // eventType -> the set of feature handlers waiting on it.
  const handlers = new Map<string, Set<Handler>>();
  // The single DOM listener attached per event type (forwards to every handler).
  const domListeners = new Map<string, (e: MessageEvent) => void>();

  let connected = $state(false);
  // True once the stream has failed to (re)connect for DEGRADE_GRACE_MS — surfaced to the
  // UI as a "live updates unavailable, likely too many open tabs" warning.
  let degraded = $state(false);
  let degradeTimer: ReturnType<typeof setTimeout> | null = null;

  function totalHandlers(): number {
    let n = 0;
    for (const set of handlers.values()) n += set.size;
    return n;
  }

  function attachDomListener(type: string): void {
    if (!source || domListeners.has(type)) return;
    const fn = (event: MessageEvent) => {
      const set = handlers.get(type);
      if (!set) return;
      // Copy so a handler that unsubscribes mid-dispatch doesn't mutate the live set.
      for (const handler of [...set]) handler(event);
    };
    domListeners.set(type, fn);
    source.addEventListener(type, fn);
  }

  function clearDegradeTimer(): void {
    if (degradeTimer) {
      clearTimeout(degradeTimer);
      degradeTimer = null;
    }
  }

  function open(): void {
    if (typeof EventSource === 'undefined') return; // SSR guard
    workspace = currentWorkspace();
    const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : '';
    const src = new EventSource(`${base}${KNOWLEDGE_EVENTS_PATH}${query}`);
    source = src;
    // (Re)attach listeners for every type subscribed so far.
    for (const type of handlers.keys()) attachDomListener(type);
    src.onopen = () => {
      connected = true;
      degraded = false;
      clearDegradeTimer();
    };
    src.onerror = () => {
      connected = false;
      // EventSource auto-reconnects; only warn if it stays down past the grace window.
      // A persistent failure here most often means the browser's per-origin HTTP/1.1
      // connection cap is exhausted (too many admin tabs / streams open).
      if (!degradeTimer) {
        degradeTimer = setTimeout(() => {
          degradeTimer = null;
          if (!connected) degraded = true;
        }, DEGRADE_GRACE_MS);
      }
    };
  }

  function close(): void {
    source?.close();
    source = null;
    domListeners.clear();
    connected = false;
    clearDegradeTimer();
    degraded = false;
  }

  function ensureOpen(): void {
    // Reopen if the selected workspace changed since we connected.
    if (source && workspace !== currentWorkspace()) close();
    if (!source) open();
  }

  /** Subscribe one handler to one event type. Returns an unsubscribe fn. */
  function subscribe(eventType: string, handler: Handler): () => void {
    let set = handlers.get(eventType);
    if (!set) {
      set = new Set();
      handlers.set(eventType, set);
    }
    set.add(handler);
    ensureOpen();
    attachDomListener(eventType);
    return () => {
      const current = handlers.get(eventType);
      if (current) {
        current.delete(handler);
        if (current.size === 0) handlers.delete(eventType);
      }
      // Last subscriber out closes the shared connection (frees the budget).
      if (totalHandlers() === 0) close();
    };
  }

  /** Subscribe one handler to many event types; returns a single combined teardown. */
  function subscribeMany(eventTypes: readonly string[], handler: Handler): () => void {
    const offs = eventTypes.map((type) => subscribe(type, handler));
    return () => {
      for (const off of offs) off();
    };
  }

  return {
    subscribe,
    subscribeMany,
    get connected() {
      return connected;
    },
    get degraded() {
      return degraded;
    }
  };
}

/** Per-tab singleton. All knowledge features share this one connection. */
export const knowledgeEventStream = createKnowledgeEventStream();
