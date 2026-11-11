// Something the user starts on one of many items (save this camera, remove this person, test this profile): busy and
// the error are kept per item, so one row's button waits while the others stay free, and an error shows under its row.
// `Action` is the same for a single thing. UI kit, step 4: the pages kept a `busy` key and an `error` record by hand.
import { errorMessage } from '$kit/api/client';

export class KeyedAction {
	/** The keys with a run going. */
	#busy = $state<Record<string, boolean>>({});
	/** What went wrong in the last run of each key. */
	#errors = $state<Record<string, string>>({});
	/** What the last run of a key did, when it said (a run that returns text). */
	#done = $state<Record<string, string>>({});
	readonly #then?: (key: string) => unknown;

	/** `then`: after every run that worked (e.g. read the list again). Its own failure counts as the run's. */
	constructor(options: { then?: (key: string) => unknown } = {}) {
		this.#then = options.then;
	}

	/** Run `fn` for `key`. Resolves with its result, or undefined when it failed. Never rejects. */
	run = async <R>(key: string, fn: () => Promise<R>): Promise<R | undefined> => {
		this.#busy[key] = true;
		this.#errors[key] = this.#done[key] = '';
		try {
			const result = await fn();
			if (typeof result === 'string') this.#done[key] = result;
			await this.#then?.(key);
			return result;
		} catch (e) {
			this.#errors[key] = errorMessage(e);
			return undefined;
		} finally {
			this.#busy[key] = false;
		}
	};

	/** A run for this key is going. */
	busy = (key: string): boolean => !!this.#busy[key];
	/** Any run is going (to disable something that works on all). */
	get anyBusy(): boolean {
		return Object.values(this.#busy).some(Boolean);
	}
	/** What went wrong in the last run of this key; '' when it worked. */
	error = (key: string): string => this.#errors[key] ?? '';
	/** The last result of this key as one line to show, or null: the error, else what it did. */
	result = (key: string): { text: string; error: boolean } | null => {
		if (this.#errors[key]) return { text: this.#errors[key], error: true };
		return this.#done[key] ? { text: this.#done[key], error: false } : null;
	};
	/** Forget a key's last result (its form closed). */
	clear = (key: string) => {
		this.#errors[key] = this.#done[key] = '';
	};
}
