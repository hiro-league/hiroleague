import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { poll, repeat } from '$kit/state/poll.svelte';

const setHidden = (hidden: boolean) => {
	(document as unknown as { hidden: boolean }).hidden = hidden;
	document.dispatchEvent(new Event('visibilitychange'));
};

beforeEach(() => {
	vi.useFakeTimers();
	vi.stubGlobal('document', Object.assign(new EventTarget(), { hidden: false }));
});
afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('repeat', () => {
	it('never runs twice at once: a slow run makes the next ticks wait', async () => {
		let finish!: () => void;
		let runs = 0;
		const stop = repeat(() => (runs++, new Promise<void>((ok) => (finish = ok))), 1000);
		await vi.advanceTimersByTimeAsync(3500);
		expect(runs).toBe(1);
		finish();
		await vi.advanceTimersByTimeAsync(1000);
		expect(runs).toBe(2);
		stop();
	});

	it('rests while the tab is hidden and runs once when it shows', async () => {
		const fn = vi.fn();
		const stop = repeat(fn, 1000);
		setHidden(true);
		await vi.advanceTimersByTimeAsync(5000);
		expect(fn).not.toHaveBeenCalled();
		setHidden(false);
		await vi.advanceTimersByTimeAsync(0);
		expect(fn).toHaveBeenCalledTimes(1);
		stop();
	});

	it('stops', async () => {
		const fn = vi.fn();
		repeat(fn, 1000)();
		await vi.advanceTimersByTimeAsync(5000);
		expect(fn).not.toHaveBeenCalled();
	});
});

describe('poll', () => {
	it('runs only while its condition holds', async () => {
		const fn = vi.fn();
		let running = $state(false);
		const stop = $effect.root(() => poll(fn, 1000, () => running));
		await tick();
		await vi.advanceTimersByTimeAsync(3000);
		expect(fn).not.toHaveBeenCalled();
		running = true;
		await tick();
		await vi.advanceTimersByTimeAsync(2000);
		expect(fn).toHaveBeenCalledTimes(2);
		running = false;
		await tick();
		await vi.advanceTimersByTimeAsync(3000);
		expect(fn).toHaveBeenCalledTimes(2);
		stop();
	});
});
