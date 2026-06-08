import { base } from '$app/paths';
import { PREF_KEYS } from '$lib/preferences/keys';

export type ApiResponse<T> = {
  ok: boolean;
  error: string | null;
  data: T;
  hosting_workspace_id?: string | null;
};

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

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {}
): Promise<ApiResponse<T>> {
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
    if (timedOut) {
      throw new Error(
        `Request timed out after ${Math.round(timeoutMs / 1000)}s — the server may be busy or ` +
          `too many browser tabs are open (each holds a live event stream). Close extra tabs and retry.`
      );
    }
    throw err; // caller-initiated cancel (component unmount / superseded) or a genuine network error
  }

  let payload: ApiResponse<T>;
  try {
    payload = (await response.json()) as ApiResponse<T>;
  } catch {
    throw new Error(`HTTP ${response.status}`);
  }

  if (!response.ok || !payload.ok) {
    throw new Error(payload.error ?? `HTTP ${response.status}`);
  }

  return payload;
}
