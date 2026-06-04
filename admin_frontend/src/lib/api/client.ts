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
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs ?? 20000);
  // Cancel too if the caller's signal fires (forwards an external abort to the fetch).
  if (options.signal) {
    if (options.signal.aborted) controller.abort();
    else options.signal.addEventListener('abort', () => controller.abort(), { once: true });
  }

  const response = await fetch(`${apiBase}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: controller.signal
  }).finally(() => window.clearTimeout(timeout));

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
