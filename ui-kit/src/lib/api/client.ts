// UI kit, step 1: only the call itself is here, so this file is the same in every Hiro app; the app's own shapes
// and calls are in the other files of lib/api (HomeHiro's general ones: api/home.ts).
import { resolve } from '$app/paths';
import { APP } from '$hiro-app/app';

// Built from the app's base URL, so calls keep working behind a proxy prefix (e.g. HA's sidebar).
export const apiUrl = (path: string) => `${resolve('/')}api/${path}`;

/** FastAPI's error detail as words: a string as it is; a list of validation errors (a 422) as
 * "where: what" lines, e.g. "count: Input should be greater than 0". */
function errorText(detail: unknown): string | null {
	if (typeof detail === 'string') return detail;
	if (!Array.isArray(detail)) return null;
	return detail
		.map((e: { loc?: unknown[]; msg?: string }) => `${(e.loc ?? []).filter((p) => p !== 'body').join('.')}: ${e.msg ?? 'invalid'}`)
		.join('; ');
}

/** A failed call: `status` is the HTTP status (0 = the backend could not be reached, e.g. it is
 * restarting), `message` FastAPI's detail as words. */
export class ApiError extends Error {
	constructor(
		readonly status: number,
		message: string
	) {
		super(message);
		this.name = 'ApiError';
	}
}

/** Words for any error, to show as it is. */
export const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** True for a call cancelled on purpose (its AbortSignal fired): nothing to show. */
export const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError';

type Init = {
	method?: string;
	/** Sent as JSON, except FormData (a file upload), which goes as it is. */
	body?: unknown;
	/** Cancels the call, e.g. when a newer one replaces it; it then rejects with an AbortError. */
	signal?: AbortSignal;
	/** Give up after this long, in ms, instead of the app's `timeoutMs`. */
	timeoutMs?: number;
};

/** What an app's backend needs around every call (lib/app/app.ts's `api`; all optional). UI kit, step 1c: the
 * HiroLeague admin's own client did these by hand; here one client does them for any app. */
export type ApiHooks = {
	/** Give up on a call after this long, in ms (none: wait as long as the browser does). */
	timeoutMs?: number;
	/** Headers for every call, read when it is made (e.g. which workspace is picked). */
	headers?: () => Record<string, string>;
	/** The backend couldn't be reached or answered 5xx: the app may start checking whether it is up. */
	onUnreachable?: (path: string) => void;
	/** The backend answered 401: the session is gone. */
	onSignedOut?: (path: string) => void;
};

/** A client for an app's backend. Every Hiro backend answers the same way: the data itself, and for a failure an
 * HTTP status with FastAPI's `detail`. */
export function createApi(hooks: ApiHooks = {}) {
	return async function api<T>(path: string, init?: Init): Promise<T> {
		const body = init?.body;
		const form = body instanceof FormData;
		const headers: Record<string, string> = { ...hooks.headers?.() };
		if (body !== undefined && !form) headers['Content-Type'] = 'application/json';
		// Our own stop for a call that takes too long, beside the caller's: which one fired says what to tell.
		const limit = init?.timeoutMs ?? hooks.timeoutMs;
		const stop = new AbortController();
		let timedOut = false;
		const timer = limit ? setTimeout(() => ((timedOut = true), stop.abort()), limit) : undefined;
		const cancel = () => stop.abort();
		if (init?.signal?.aborted) stop.abort();
		else init?.signal?.addEventListener('abort', cancel, { once: true });
		let res: Response;
		try {
			res = await fetch(apiUrl(path), {
				method: init?.method ?? 'GET',
				headers: Object.keys(headers).length ? headers : undefined,
				body: body === undefined ? undefined : form ? body : JSON.stringify(body),
				signal: limit || init?.signal ? stop.signal : undefined
			});
		} catch (e) {
			// A call that ran out of time is not the backend being down (it may only be busy): say so, start no check.
			if (timedOut) throw new ApiError(0, `${APP.name} took more than ${Math.round(limit! / 1000)} s to answer. It may be busy: try again.`);
			if (isAbort(e)) throw e;
			hooks.onUnreachable?.(path);
			throw new ApiError(0, `The ${APP.name} backend can't be reached. Is it restarting?`);
		} finally {
			clearTimeout(timer);
			init?.signal?.removeEventListener('abort', cancel);
		}
		const data = await res.json().catch(() => ({}));
		if (!res.ok) {
			if (res.status === 401) hooks.onSignedOut?.(path);
			if (res.status >= 500) hooks.onUnreachable?.(path);
			throw new ApiError(res.status, errorText(data.detail) ?? `${res.status} ${res.statusText}`);
		}
		return data as T;
	};
}

/** The app's backend: `api<Thing>('things')`, `api('things/1', { method: 'PUT', body })`. */
export const api = createApi(APP.api);
