import { base } from '$app/paths';
import { PREF_KEYS } from '$lib/preferences/keys';
import { signalServerMaybeUnavailable } from '$lib/runtime/server-stale-signal';
import { signalSignedOut } from '$lib/runtime/sign-in-signal';

const apiBase = `${base}/api`;

type RequestOptions = {
  method?: string;
  body?: unknown;
  timeoutMs?: number;
  // Optional caller-owned signal so a component can cancel an in-flight request
  // (e.g. selection changed / panel unmounted) instead of leaking the connection.
  // Combined with the internal timeout controller below.
  signal?: AbortSignal;
};

/** Kick the shared readiness poller — skip the poller's own probe to avoid a feedback loop. */
function maybeMarkServerStale(path: string): void {
  if (path === '/runtime/status') return;
  signalServerMaybeUnavailable();
}

/**
 * The words of a failure body: FastAPI's `{"detail": "<words>"}`, or its list of validation errors
 * (`[{loc, msg}, ...]`) joined as "where: what". Null when the body carries neither.
 */
function failureWords(payload: unknown): string | null {
  if (typeof payload !== 'object' || payload === null) return null;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === 'string') return detail || null;
  if (Array.isArray(detail)) {
    const lines = detail.map((item) => {
      if (typeof item === 'string') return item;
      if (typeof item !== 'object' || item === null) return String(item);
      const { loc, msg } = item as { loc?: unknown; msg?: unknown };
      // "body" / "query" only say where in the request; the field name after it is what a person needs.
      const where = Array.isArray(loc)
        ? loc.filter((part) => part !== 'body' && part !== 'query' && part !== 'path').join('.')
        : '';
      const what = typeof msg === 'string' ? msg : JSON.stringify(item);
      return where ? `${where}: ${what}` : what;
    });
    return lines.join('; ') || null;
  }
  return null;
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const selectedWorkspace =
    typeof localStorage === 'undefined' ? null : localStorage.getItem(PREF_KEYS.selectedWorkspace);
  const headers = new Headers();
  if (options.body !== undefined) {
    headers.set('content-type', 'application/json');
  }
  if (selectedWorkspace) {
    // Future workspace-scoped APIs can read this without coupling UI prefs to URL shape.
    headers.set('x-hiro-workspace', selectedWorkspace);
  }

  const controller = new AbortController();
  // Track whether OUR timeout (not the caller's signal) aborted the request, so the abort
  // can be surfaced as a readable "timed out / server busy" message instead of the raw
  // DOMException "signal is aborted without reason".
  const timeoutMs = options.timeoutMs ?? 20000;
  let timedOut = false;
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  // Cancel too if the caller's signal fires (forwards an external abort to the fetch).
  if (options.signal) {
    if (options.signal.aborted) controller.abort();
    else options.signal.addEventListener('abort', () => controller.abort(), { once: true });
  }

  let response: Response;
  try {
    response = await fetch(`${apiBase}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal
    }).finally(() => window.clearTimeout(timeout));
  } catch (err) {
    // Our timeout fired → readable, actionable message (the request never completed,
    // often because too many open tabs/SSE streams saturate the browser connection pool).
    // NOTE: do NOT mark the server stale on timeout. In this app a timeout overwhelmingly
    // means the per-origin connection pool is saturated (too many tabs), not a server
    // outage — and the readiness probe would travel the same saturated pool and also time
    // out, leaving a sticky-yet-false "Server unavailable" banner. Genuine outages are
    // caught by the connection-refused (network) and 5xx branches below.
    if (timedOut) {
      throw new Error(
        `Request timed out after ${Math.round(timeoutMs / 1000)}s — the server may be busy or ` +
          `too many browser tabs are open (each holds a live event stream). Close extra tabs and retry.`
      );
    }
    // Caller-initiated cancel (component unmount / superseded) — not a server outage.
    if (options.signal?.aborted) {
      throw err;
    }
    maybeMarkServerStale(path);
    throw err;
  }

  // UI kit step 1d (completes backend commit fd0c06b0): an answer is the data itself; a failure is an
  // HTTP status with FastAPI's body {"detail": ...}. The old {ok, error, data} wrapper is gone, so this
  // returns the parsed body and throws the failure's words.
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    if (response.status >= 500) {
      maybeMarkServerStale(path);
    }
    // A 2xx with no JSON body is not something any route sends; say so like any other failure.
    throw new Error(`HTTP ${response.status}`);
  }

  if (!response.ok) {
    // Phase 6: the admin has its own sign-in; a 401 outside /auth/ means the session is gone.
    if (response.status === 401 && !path.startsWith('/auth/')) {
      signalSignedOut();
    }
    if (response.status >= 500) {
      maybeMarkServerStale(path);
    }
    throw new Error(failureWords(payload) ?? `HTTP ${response.status}`);
  }

  return payload as T;
}
