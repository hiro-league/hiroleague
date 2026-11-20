// A page's problems, sent to its app's log (the logging plan's phase 8: browser pages join as sources). The backend
// kit takes them at /api/page-problems (page_problems.py) and writes each as a line of the app's own log, under the
// story it belongs to, so a person or an agent reading the logs sees what went wrong in the browser beside what the
// backend did.
//
// What is reported: an error nobody caught (error-bar.svelte), a page that stopped drawing (the shell's boundary) or
// couldn't open (hooks.client.ts), and a call to the backend that got no answer or a 5xx (client.ts). A 4xx is the
// backend's own answer, shown to the person: not a problem of the system, so not reported.
//
// The story: every call to the backend sends a W3C `traceparent` the page makes (client.ts), which the backend
// continues, so a failed call's report and the backend's lines for it share one id. An error that came from a call
// (an ApiError) keeps that call's id; any other error starts a story of its own.
//
// Only the page's path (never its query, which can hold a sign-in code), the error's name, message and stack, and a
// call's method, path and status are sent. Reports are batched, the same problem again is counted, and a page sends at
// most 30 a minute. A report that fails is kept for the next try (at most 50 waiting) and never reported itself.
import type { HandleClientError } from '@sveltejs/kit';
import { apiUrl, errorMessage } from './client';

export type ProblemKind = 'error' | 'page' | 'request';

export type Problem = {
	kind: ProblemKind;
	level: 'WARNING' | 'ERROR';
	message: string;
	error_type?: string;
	stack?: string;
	page: string;
	traceparent: string;
	at: string;
	count: number;
	method?: string;
	path?: string;
	status?: number;
};

const BATCH_MS = 2000;
const PER_MINUTE = 30;
const WAITING_MAX = 50;
const BATCH_MAX = 20; // the backend takes at most 20 at once

const hex = (bytes: number) =>
	Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(16).padStart(2, '0')).join('');

/** A new story's first step, as a W3C traceparent: `00-<32 hex story id>-<16 hex step id>-01`. */
export function newTraceparent(): string {
	let story = hex(16);
	while (/^0+$/.test(story)) story = hex(16); // all zeros is not a valid id
	return `00-${story}-${hex(8)}-01`;
}

/** The story id (32 hex digits) in a traceparent, or '' when there is none. */
export const storyOf = (traceparent: string | undefined) => traceparent?.split('-')[1] ?? '';

const cut = (text: string, size: number) => (text.length <= size ? text : text.slice(0, size - 1) + '…');
const noQuery = (path: string) => path.split(/[?#]/, 1)[0];

let waiting: Problem[] = [];
let timer: ReturnType<typeof setTimeout> | undefined;
let sending = false;
let minute = { start: 0, count: 0 };

function room(): boolean {
	const now = Date.now();
	if (now - minute.start >= 60_000) minute = { start: now, count: 0 };
	if (minute.count >= PER_MINUTE) return false;
	minute.count++;
	return true;
}

async function flush(keepalive = false) {
	timer = undefined;
	if (sending || !waiting.length) return;
	const batch = waiting.slice(0, BATCH_MAX);
	sending = true;
	try {
		const res = await fetch(apiUrl('page-problems'), {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ problems: batch }),
			keepalive
		});
		// Taken (or refused for good: signed out, or an app with no such route): either way not sent again.
		if (res.ok || (res.status >= 400 && res.status < 500)) waiting = waiting.filter((p) => !batch.includes(p));
	} catch {
		// The backend can't be reached: keep them for the next report (never reported themselves).
	} finally {
		sending = false;
	}
	if (waiting.length) schedule();
}

function schedule() {
	if (timer === undefined) timer = setTimeout(() => void flush(), BATCH_MS);
}

/** Report a problem to the app's log. Never throws. */
export function report(p: Omit<Problem, 'page' | 'at' | 'count' | 'traceparent'> & { traceparent?: string }) {
	try {
		const message = cut(p.message || 'Something went wrong.', 2000);
		const path = p.path ? cut(noQuery(p.path), 500) : undefined;
		const same = waiting.find((w) => w.kind === p.kind && w.message === message && w.path === path);
		if (same) {
			same.count++;
			return;
		}
		if (!room()) return;
		waiting.push({
			...p,
			message,
			error_type: p.error_type ? cut(p.error_type, 200) : undefined,
			stack: p.stack ? cut(p.stack, 8000) : undefined,
			path,
			page: cut(noQuery(location.pathname), 500),
			traceparent: p.traceparent || newTraceparent(),
			at: new Date().toISOString(),
			count: 1
		});
		if (waiting.length > WAITING_MAX) waiting = waiting.slice(-WAITING_MAX);
		schedule();
	} catch {
		// A report must never become a page's problem of its own.
	}
}

/** Report an error the page didn't catch (kind `error`), or a page that stopped working (kind `page`). An error from
 * a call to the backend keeps that call's story; one the call reported already (no answer, a 5xx) isn't sent twice. */
export function reportError(e: unknown, kind: 'error' | 'page' = 'error') {
	const call = e as { name?: string; status?: number; traceparent?: string } | null;
	if (call?.name === 'ApiError' && (call.status === 0 || (call.status ?? 0) >= 500)) return;
	const err = e instanceof Error ? e : null;
	report({
		kind,
		level: 'ERROR',
		message: err ? err.message : String(e),
		error_type: err ? err.name : typeof e,
		stack: err?.stack,
		traceparent: call?.traceparent
	});
}

/** Every app's hooks.client.ts: what the app shows when a page can't be opened (an unknown address, or a throw while
 * SvelteKit loads it), a readable message on the error page (routes/+error.svelte); and the app's log hears of it.
 * Errors while a page runs are caught by the layout (a failed page, or the error bar). */
export const handleError: HandleClientError = ({ error, status, message }) => {
	if (status === 404) return { message: 'There is no page at this address.' };
	console.error(error);
	reportError(error, 'page');
	return { message: errorMessage(error) || message };
};

if (typeof window !== 'undefined') {
	// Leaving the page: what waits goes now, in a request the browser finishes after the page is gone.
	window.addEventListener('pagehide', () => void flush(true));
}

/** For the kit's tests: forget what waits. */
export function resetProblems() {
	waiting = [];
	clearTimeout(timer);
	timer = undefined;
	sending = false;
	minute = { start: 0, count: 0 };
}

/** For the kit's tests: send what waits now. */
export const flushProblems = () => flush();
