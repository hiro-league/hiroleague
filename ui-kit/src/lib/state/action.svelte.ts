// Something the user starts (save, sync, test, remove): busy while it runs, then what it did or
// what went wrong, for the page to show.
import { errorMessage } from '$kit/api/client';

export type ActionOptions = {
	/** After every run that worked, e.g. reload what the page shows. Its own failure counts as the
	 * action's. */
	then?: () => unknown;
	/** Called with the message when a run fails (a toast; a page that wants one line more). */
	onError?: (message: string) => void;
};

export class Action {
	/** A run is going: disable the buttons that start one. */
	busy = $state(false);
	/** What went wrong in the last run; '' when it worked. */
	error = $state('');
	/** What the last run did, when it said (a run that returns text); '' otherwise. */
	done = $state('');
	#then?: () => unknown;
	#onError?: (message: string) => void;

	constructor(options: ActionOptions = {}) {
		this.#then = options.then;
		this.#onError = options.onError;
	}

	/** Run `fn`. Resolves with its result, or undefined when it failed. Never rejects. */
	run = async <R>(fn: () => Promise<R>): Promise<R | undefined> => {
		this.busy = true;
		this.error = this.done = '';
		try {
			const result = await fn();
			if (typeof result === 'string') this.done = result;
			await this.#then?.();
			return result;
		} catch (e) {
			this.error = errorMessage(e);
			this.#onError?.(this.error);
			return undefined;
		} finally {
			this.busy = false;
		}
	};

	/** The last result as one line to show, or null: the error, else what it did. */
	get result(): { text: string; error: boolean } | null {
		if (this.error) return { text: this.error, error: true };
		return this.done ? { text: this.done, error: false } : null;
	}

	/** Forget the last result, e.g. when the form it belongs to closes. */
	clear() {
		this.error = this.done = '';
	}
}
