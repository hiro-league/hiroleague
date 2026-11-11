import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { toast } from './toast.svelte';

describe('toast', () => {
	beforeEach(() => vi.useFakeTimers());
	afterEach(() => {
		toast.clear();
		vi.useRealTimers();
	});

	it('shows a line, then lets it go by itself', () => {
		toast.success('Saved');
		expect(toast.list.map((t) => [t.kind, t.message])).toEqual([['success', 'Saved']]);
		vi.advanceTimersByTime(4500);
		expect(toast.list).toEqual([]);
	});

	it('keeps an error longer than a success', () => {
		toast.error('Could not save');
		vi.advanceTimersByTime(4500);
		expect(toast.list).toHaveLength(1);
		vi.advanceTimersByTime(4500);
		expect(toast.list).toEqual([]);
	});

	it('shows the same words once, and at most three lines', () => {
		toast.info('Copied');
		toast.info('Copied');
		expect(toast.list).toHaveLength(1);
		toast.info('a');
		toast.info('b');
		toast.info('c');
		expect(toast.list.map((t) => t.message)).toEqual(['a', 'b', 'c']);
	});

	it('goes when dismissed', () => {
		const id = toast.warning('Slow');
		toast.dismiss(id);
		expect(toast.list).toEqual([]);
	});
});
