import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { NoticeType } from '$kit/live';

// Live notices: the test sends them by hand.
const notices = vi.hoisted(() => ({ runs: [] as { types: NoticeType[]; run: () => void }[], stopped: 0 }));
vi.mock('$kit/live', () => ({
	onNotices: (types: NoticeType[], run: () => void) => {
		notices.runs.push({ types, run });
		return () => notices.stopped++;
	}
}));
const notify = (type: NoticeType) => notices.runs.filter((r) => r.types.includes(type)).forEach((r) => r.run());

import { Resource } from './resource.svelte';

/** A call the test answers when it wants: `calls[i].ok(value)` or `.fail(error)`. */
function controlled<T>() {
	const calls: { signal: AbortSignal; ok: (v: T) => void; fail: (e: unknown) => void }[] = [];
	const fetcher = (signal: AbortSignal) =>
		new Promise<T>((ok, fail) => {
			calls.push({ signal, ok, fail });
		});
	return { calls, fetcher };
}
const settle = () => new Promise((r) => setTimeout(r, 0));

// A Resource lives in a component; $effect.root stands in for one here.
let stop: () => void = () => {};
async function mount<T>(make: () => Resource<T>): Promise<Resource<T>> {
	let r!: Resource<T>;
	stop = $effect.root(() => {
		r = make();
	});
	await tick(); // the first effects run: the first load starts
	return r;
}

beforeEach(() => {
	notices.runs = [];
	notices.stopped = 0;
	vi.stubGlobal('document', Object.assign(new EventTarget(), { hidden: false }));
});
afterEach(() => {
	stop();
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('Resource', () => {
	it('loads when created', async () => {
		const { calls, fetcher } = controlled<string>();
		const r = await mount(() => new Resource(fetcher));
		expect(r.loading).toBe(true);
		calls[0].ok('hello');
		await settle();
		expect(r.data).toBe('hello');
		expect(r.loading).toBe(false);
		expect(r.error).toBe('');
	});

	it('keeps the data it had when a reload fails, and says why', async () => {
		let fail = false;
		const r = await mount(() => new Resource(async () => (fail ? Promise.reject(new Error('backend down')) : 'v1')));
		await settle();
		fail = true;
		await r.reload();
		expect(r.data).toBe('v1');
		expect(r.error).toBe('backend down');
		fail = false;
		await r.reload();
		expect(r.error).toBe('');
	});

	it('drops the answer of a load that a newer one replaced, and cancels it', async () => {
		const { calls, fetcher } = controlled<string>();
		const r = await mount(() => new Resource(fetcher));
		void r.reload();
		expect(calls).toHaveLength(2);
		expect(calls[0].signal.aborted).toBe(true);
		calls[1].ok('new');
		calls[0].ok('old'); // late
		await settle();
		expect(r.data).toBe('new');
	});

	it('loads again when an input changes, and the old input’s answer is dropped', async () => {
		let floor = $state('ground');
		const seen: string[] = [];
		const { calls, fetcher } = controlled<string>();
		const r = await mount(
			() =>
				new Resource((signal) => {
					seen.push(floor); // read before any await: an input
					return fetcher(signal);
				})
		);
		floor = 'first';
		await tick();
		expect(seen).toEqual(['ground', 'first']);
		calls[1].ok('first floor');
		calls[0].ok('ground floor'); // late
		await settle();
		expect(r.data).toBe('first floor');
	});

	it('drops the data shown when an input changes, keeps it for a reload', async () => {
		let floor = $state('ground');
		const { calls, fetcher } = controlled<string>();
		const r = await mount(() => new Resource((signal) => (void floor, fetcher(signal))));
		calls[0].ok('ground floor');
		await settle();
		void r.reload();
		expect(r.data).toBe('ground floor');
		floor = 'first';
		await tick();
		expect(r.data).toBeNull();
	});

	it('does not count a cancelled call as an error', async () => {
		const { calls, fetcher } = controlled<string>();
		const r = await mount(() => new Resource(fetcher));
		void r.reload();
		calls[0].fail(new DOMException('aborted', 'AbortError'));
		calls[1].ok('fine');
		await settle();
		expect(r.error).toBe('');
		expect(r.data).toBe('fine');
	});

	it('reloads after its notices, not others', async () => {
		let n = 0;
		const r = await mount(() => new Resource(async () => ++n, { on: ['streams'] }));
		await settle();
		notify('states');
		await settle();
		expect(r.data).toBe(1);
		notify('streams');
		await settle();
		expect(r.data).toBe(2);
	});

	it('reloads every so often, but not while the tab is hidden, and catches up when it shows', async () => {
		vi.useFakeTimers();
		let n = 0;
		const r = await mount(() => new Resource(async () => ++n, { every: 1000 }));
		await vi.advanceTimersByTimeAsync(0);
		expect(r.data).toBe(1);
		await vi.advanceTimersByTimeAsync(1000);
		expect(r.data).toBe(2);
		(document as unknown as { hidden: boolean }).hidden = true;
		await vi.advanceTimersByTimeAsync(3000);
		expect(r.data).toBe(2);
		(document as unknown as { hidden: boolean }).hidden = false;
		document.dispatchEvent(new Event('visibilitychange'));
		await vi.advanceTimersByTimeAsync(0);
		expect(r.data).toBe(3);
	});

	it('stops with its component: no notices, no timer, the running call cancelled', async () => {
		vi.useFakeTimers();
		const { calls, fetcher } = controlled<string>();
		await mount(() => new Resource(fetcher, { on: ['sync'], every: 1000 }));
		stop();
		expect(notices.stopped).toBe(1);
		expect(calls[0].signal.aborted).toBe(true);
		await vi.advanceTimersByTimeAsync(5000);
		expect(calls).toHaveLength(1);
	});

	it('set() shows data without loading, and wins over a load still running', async () => {
		const { calls, fetcher } = controlled<string>();
		const r = await mount(() => new Resource(fetcher));
		r.set('saved');
		calls[0].ok('loaded before the save');
		await settle();
		expect(r.data).toBe('saved');
		expect(r.loading).toBe(false);
	});
});
