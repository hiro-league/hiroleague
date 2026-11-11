// Notices from the backend (Server-Sent Events on /api/events, live.py's `Browsers`):
// Which notices this app's backend sends, and what each means: lib/app/notices.ts.
//
// The page keeps ONE stream open, shared by every card and page that listens: opened for the first
// listener, closed a moment after the last one leaves (so moving between pages keeps it). Browsers
// allow only a few connections per server, and every open stream holds one.
//
// The stream ends whenever the backend stops (a deploy, or a dev reload: live.py ends every stream so
// the stop isn't held). EventSource reconnects by itself after a network error, but not after an HTTP
// error (a proxy's 502 while the backend is down): then the page opens a new stream a moment later.
// The backend also pings every 15 s; a stream silent much longer is dead without saying so (Vite's dev
// proxy keeps it "open" after the backend is cut off), and is replaced too.
import { resolve } from '$app/paths';
import { NOTICE_TYPES } from '$hiro-app/notices';

// UI kit, step 1: the notice types are the app's own (lib/app/notices.ts), so this file is the same in every Hiro app.
const TYPES = NOTICE_TYPES;
export type NoticeType = (typeof TYPES)[number];
// A notice is only its type here: what else the backend puts in one (HomeHiro's "hello" carries its HA
// connection) no listener reads, so the stream stays the same for an app without it.
export type Notice = { type: NoticeType };

const isNotice = (v: unknown): v is Notice =>
	!!v && typeof v === 'object' && (TYPES as readonly string[]).includes((v as { type: unknown }).type as string);

const listeners = new Set<(n: Notice) => void>();
let source: EventSource | null = null;
let closing: ReturnType<typeof setTimeout> | undefined;
let retrying: ReturnType<typeof setTimeout> | undefined;
let silence: ReturnType<typeof setTimeout> | undefined;
const CLOSE_AFTER = 2000; // ms without listeners before the stream is closed
const RETRY_AFTER = 5000; // ms before a new stream, after the browser gave one up
const SILENT_AFTER = 45_000; // ms without a word (3 missed pings) before a stream counts as dead

/** `comeback`: an earlier stream was lost, so its notices may have been missed. */
function open(comeback = false) {
	const es = new EventSource(`${resolve('/')}api/events`);
	// The backend greets every new stream with "hello". The first greeting is not passed on: whoever
	// listens has just loaded what it shows. A later one means the stream dropped and came back
	// (EventSource reconnects by itself), and notices may have been missed meanwhile. So does a first
	// one after failed tries (the backend was down, and the first loads probably failed too), and the
	// first one of a stream that replaces a lost one.
	let greeted = false;
	let failed = comeback;
	const alive = () => {
		clearTimeout(silence);
		silence = setTimeout(() => replace(es), SILENT_AFTER);
	};
	alive();
	es.addEventListener('ping', alive);
	es.onerror = () => {
		failed = true;
		if (es.readyState !== EventSource.CLOSED) return; // it reconnects by itself
		clearTimeout(silence);
		clearTimeout(retrying);
		retrying = setTimeout(() => replace(es), RETRY_AFTER);
	};
	es.onmessage = (e) => {
		alive();
		let n: unknown;
		try {
			n = JSON.parse(e.data);
		} catch {
			return; // a malformed notice
		}
		if (!isNotice(n)) return;
		if (n.type === 'hello' && !greeted) {
			greeted = true;
			if (!failed) return;
		}
		for (const l of [...listeners]) l(n);
	};
	source = es;
}

/** A new stream for one that was lost, unless it was closed or replaced meanwhile. */
function replace(lost: EventSource) {
	if (source !== lost) return;
	lost.close();
	open(true);
}

function close() {
	clearTimeout(retrying);
	clearTimeout(silence);
	source?.close();
	source = null;
}

/** Hear every notice. Returns the function that stops listening. */
export function listen(onNotice: (n: Notice) => void): () => void {
	clearTimeout(closing);
	listeners.add(onNotice);
	if (!source) open();
	return () => {
		listeners.delete(onNotice);
		if (listeners.size) return;
		clearTimeout(closing);
		closing = setTimeout(() => {
			if (!listeners.size) close();
		}, CLOSE_AFTER);
	};
}

/** Run `run` after notices of these types, once per burst (notices often come several at a time).
 * Returns the function that stops it, including a run still waiting. Call from onMount or $effect. */
export function onNotices(types: NoticeType[], run: () => void, debounceMs = 250): () => void {
	let timer: ReturnType<typeof setTimeout> | undefined;
	const stop = listen((n) => {
		if (!types.includes(n.type)) return;
		clearTimeout(timer);
		timer = setTimeout(run, debounceMs);
	});
	return () => {
		stop();
		clearTimeout(timer);
	};
}
