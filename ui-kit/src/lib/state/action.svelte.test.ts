import { describe, expect, it, vi } from 'vitest';
import { Action } from './action.svelte';

describe('Action', () => {
	it('is busy while it runs, then reports the text the run returned', async () => {
		const a = new Action();
		let finish!: (v: string) => void;
		const running = a.run(() => new Promise<string>((ok) => (finish = ok)));
		expect(a.busy).toBe(true);
		finish('Saved.');
		expect(await running).toBe('Saved.');
		expect(a.busy).toBe(false);
		expect(a.done).toBe('Saved.');
		expect(a.error).toBe('');
	});

	it('reports a failure instead of throwing, and forgets the last result', async () => {
		const a = new Action();
		await a.run(async () => 'Saved.');
		const result = await a.run(async () => {
			throw new Error('No token');
		});
		expect(result).toBeUndefined();
		expect(a.error).toBe('No token');
		expect(a.done).toBe('');
		expect(a.busy).toBe(false);
	});

	it('runs `then` after a run that worked, not after one that failed', async () => {
		const then = vi.fn();
		const a = new Action({ then });
		await a.run(async () => {});
		expect(then).toHaveBeenCalledTimes(1);
		await a.run(() => Promise.reject(new Error('no')));
		expect(then).toHaveBeenCalledTimes(1);
	});

	it('counts a failing `then` as the action’s failure', async () => {
		const a = new Action({ then: () => Promise.reject(new Error('reload failed')) });
		await a.run(async () => 'Saved.');
		expect(a.error).toBe('reload failed');
	});
});
