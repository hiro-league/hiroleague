// A toast: a short line in the corner for something that happened while the person may be looking elsewhere
// (a save that finished, a copy made, a background job's end). It leaves by itself; an error stays longer.
// One for the whole app, shown by <ToastHost /> in the shell: `toast.success('Saved')`, `toast.error(message)`.
// For the result of the button just pressed, right under it, use Feedback; for a problem with what the page
// shows, a Notice.
// UI kit, step 2: from the HiroLeague admin's createToastNotifier (one per page there; one for the app here).

export type ToastKind = 'success' | 'error' | 'warning' | 'info';
export type Toast = { id: number; kind: ToastKind; message: string };

const STAYS: Record<ToastKind, number> = { success: 4500, info: 4500, warning: 7000, error: 9000 }; // ms
const MOST = 3; // shown at once; an older one makes way

class Toasts {
	list = $state<Toast[]>([]);
	#next = 1;
	#timers = new Map<number, ReturnType<typeof setTimeout>>();

	show = (kind: ToastKind, message: string) => {
		// the same words again (a button pressed twice) replace the first, not stack under it
		for (const t of this.list.filter((t) => t.kind === kind && t.message === message)) this.dismiss(t.id);
		const id = this.#next++;
		const all = [...this.list, { id, kind, message }];
		for (const gone of all.slice(0, -MOST)) this.#forget(gone.id);
		this.list = all.slice(-MOST);
		this.#timers.set(
			id,
			setTimeout(() => this.dismiss(id), STAYS[kind])
		);
		return id;
	};
	success = (message: string) => this.show('success', message);
	error = (message: string) => this.show('error', message);
	warning = (message: string) => this.show('warning', message);
	info = (message: string) => this.show('info', message);

	dismiss = (id: number) => {
		this.#forget(id);
		this.list = this.list.filter((t) => t.id !== id);
	};
	clear = () => this.list.forEach((t) => this.dismiss(t.id));

	#forget(id: number) {
		clearTimeout(this.#timers.get(id));
		this.#timers.delete(id);
	}
}

export const toast = new Toasts();
