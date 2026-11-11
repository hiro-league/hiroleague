// Errors nobody caught: a promise that failed with no one waiting for it, or a throw in an event
// handler. Without this they only reach the console and the page just seems not to react; the error
// bar (error-bar.svelte, in the layout) shows them until dismissed.
import { errorMessage, isAbort } from '$kit/api/client';

export type AppError = { id: number; message: string; count: number };

class AppErrors {
	list = $state<AppError[]>([]);
	#next = 1;

	/** Show `e` (the same message again counts up instead of adding a line). Cancelled calls and the
	 * browser's harmless ResizeObserver notice are not errors. */
	add(e: unknown) {
		if (isAbort(e)) return;
		const message = errorMessage(e) || 'Something went wrong.';
		if (message.startsWith('ResizeObserver loop')) return;
		console.error(e);
		const same = this.list.find((x) => x.message === message);
		if (same) same.count++;
		else this.list = [...this.list, { id: this.#next++, message, count: 1 }].slice(-3);
	}

	dismiss(id: number) {
		this.list = this.list.filter((x) => x.id !== id);
	}
}

export const appErrors = new AppErrors();
