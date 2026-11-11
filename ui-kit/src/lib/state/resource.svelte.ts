// Data from the backend, kept up to date: the loading / error / reload code every page needs.
import { untrack } from 'svelte';
import { errorMessage, isAbort } from '$kit/api/client';
import { onNotices, type NoticeType } from '$kit/live';
import { repeat } from '$kit/state/poll.svelte';

export type ResourceOptions = {
	/** Load again after these live notices (a burst of them counts once). */
	on?: NoticeType[];
	/** How long to wait for a burst of notices to end, in ms. Default 250. */
	debounce?: number;
	/** Also load again this often, in ms: for values that move without a notice (times, rates).
	 * Rests while the tab is hidden, like `repeat`. */
	every?: number;
};

/**
 * Create it while a component is set up (its script); it stops with the component.
 *
 * - `fetcher` loads the data. Reactive values it reads before its first `await` are its inputs:
 *   when one changes (another floor, another stream), the data shown so far is dropped and it
 *   loads again. Reloads for notices, timers or `reload()` keep the data shown until the new one
 *   comes.
 * - Only the latest load counts: an answer that comes back after a newer load started is dropped.
 *   The older call is also cancelled when the fetcher passes `signal` on to `api()`.
 * - A failed load keeps the data already shown; `error` says what went wrong until a load succeeds.
 */
export class Resource<T> {
	/** The last data loaded; null until the first load succeeds. */
	data = $state<T | null>(null);
	/** What went wrong in the last load; '' when it worked. */
	error = $state('');
	/** A load is running. */
	loading = $state(false);
	#latest: AbortController | null = null;
	#fetcher: (signal: AbortSignal) => Promise<T>;

	constructor(fetcher: (signal: AbortSignal) => Promise<T>, options: ResourceOptions = {}) {
		this.#fetcher = fetcher;
		// Runs again when an input of the fetcher changes (see above).
		let first = true;
		$effect(() => {
			if (!first) untrack(() => ((this.data = null), (this.error = '')));
			first = false;
			void this.#load();
		});
		$effect(() =>
			untrack(() => {
				const stops: (() => void)[] = [];
				if (options.on?.length) stops.push(onNotices(options.on, () => void this.reload(), options.debounce));
				if (options.every) stops.push(repeat(this.reload, options.every));
				return () => {
					stops.forEach((stop) => stop());
					this.#latest?.abort(); // the component is gone: its answer is not wanted
				};
			})
		);
	}

	/** Load now, e.g. after a change made on this page. Never rejects: failures go to `error`. */
	reload = (): Promise<void> => untrack(() => this.#load());

	/** Show this data without loading, e.g. what a save answered with. */
	set(data: T) {
		this.#latest?.abort();
		this.#latest = null;
		this.loading = false;
		this.data = data;
		this.error = '';
	}

	#load(): Promise<void> {
		this.#latest?.abort();
		const mine = new AbortController();
		this.#latest = mine;
		this.loading = true;
		let call: Promise<T>;
		try {
			call = this.#fetcher(mine.signal);
		} catch (e) {
			call = Promise.reject(e);
		}
		return call
			.then(
				(data) => {
					if (this.#latest !== mine) return;
					this.data = data;
					this.error = '';
				},
				(e) => {
					if (this.#latest === mine && !isAbort(e)) this.error = errorMessage(e);
				}
			)
			.finally(() => {
				if (this.#latest !== mine) return;
				this.#latest = null;
				this.loading = false;
			});
	}
}
