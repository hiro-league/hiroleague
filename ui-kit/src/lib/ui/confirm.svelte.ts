// Asking before something that can't be taken back, in the app's own dialog (not the browser's
// confirm()): `if (!(await ask({ title, description, action }))) return;`. One dialog for the whole
// app, shown by <ConfirmHost /> in the layout.

export type Question = {
	title: string;
	description?: string;
	action?: string; // the button that says yes; "Continue" by default
	danger?: boolean; // the yes button in red (deleting, throwing away)
};

class Asking {
	question = $state<Question | null>(null);
	#answer: ((yes: boolean) => void) | null = null;

	ask = (q: Question): Promise<boolean> => {
		this.#answer?.(false); // a question still open is answered no
		this.question = q;
		return new Promise((resolve) => (this.#answer = resolve));
	};

	answer = (yes: boolean) => {
		const done = this.#answer;
		this.#answer = null;
		this.question = null;
		done?.(yes);
	};
}

export const asking = new Asking();

/** Ask a yes / no question in the app's dialog; true when the yes button was pressed. */
export const ask = asking.ask;
