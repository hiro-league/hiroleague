// Editing something that is saved: a copy to edit (the draft), the saved one, whether they differ, Save and Undo.
// Every editor wrote this by hand (a `saved`, a `draft`, a JSON compare, a busy flag, an error line, "leave without
// saving?"). UI kit, step 4.
//
//   const form = new Draft<Activity[]>([], { save: (d) => putActivities(d) });   // in a component's script
//   form.load(await getActivities());       // what is saved; an edited draft keeps its edits, an unedited one follows
//   <input bind:value={form.value[0].name} />
//   <Button disabled={!form.dirty || form.action.busy} onclick={form.save}>Save</Button>
//   <Button onclick={form.undo} disabled={!form.dirty}>Undo changes</Button>
//
// Leaving the page with changes asks first (guardUnsaved), unless `guard: false`: set that when the draft is one of
// several (Drafts asks once for all of them) or when it is made outside a component's setup.
import { guardUnsaved } from '$kit/ui/unsaved.svelte';
import { Action } from './action.svelte';

export type DraftOptions<T> = {
	/** Copy a value: the draft must not share objects with what is saved. Default: structuredClone. */
	clone?: (v: T) => T;
	/** Are two values the same? Default: the same JSON. */
	equal?: (a: T, b: T) => boolean;
	/** Save the draft; resolves with what is saved now (the answer), or nothing (then the draft is what is saved). */
	save?: (draft: T) => Promise<T | void>;
	/** Ask before leaving the page with unsaved changes. Default true. */
	guard?: boolean;
};

const sameJson = <T>(a: T, b: T) => JSON.stringify(a) === JSON.stringify(b);

export class Draft<T> {
	/** The saved value; null until `load` (or a first save) gave one. */
	saved = $state<T | null>(null);
	/** The copy being edited. Bind to it. */
	value = $state() as T;
	/** The save in progress, and what went wrong in the last one. */
	readonly action = new Action();
	readonly #initial: T;
	readonly #clone: (v: T) => T;
	readonly #equal: (a: T, b: T) => boolean;
	readonly #save?: (draft: T) => Promise<T | void>;

	/** `initial`: what to edit before anything is saved (a blank form). */
	constructor(initial: T, options: DraftOptions<T> = {}) {
		this.#clone = options.clone ?? ((v) => structuredClone($state.snapshot(v)) as T);
		this.#equal = options.equal ?? sameJson;
		this.#save = options.save;
		this.#initial = this.#clone(initial);
		this.value = this.#clone(initial);
		if (options.guard !== false) guardUnsaved(() => this.dirty);
	}

	/** The draft differs from what is saved (or from `initial`, while nothing is saved). */
	get dirty(): boolean {
		return !this.#equal(this.value, this.saved ?? this.#initial);
	}

	/**
	 * What is saved now (read again, changed elsewhere, or just saved). An unedited draft follows it; an edited one
	 * keeps its edits unless `discard` is true.
	 */
	load(saved: T, discard = false) {
		const edited = this.dirty;
		this.saved = this.#clone(saved);
		if (discard || !edited) this.value = this.#clone(saved);
	}

	/** Throw the edits away: the draft is what is saved again. */
	undo = () => {
		this.value = this.#clone(this.saved ?? this.#initial);
	};

	/** Save the draft. Resolves true when it worked; the error, if not, is `action.error`. */
	save = async (): Promise<boolean> => {
		const save = this.#save;
		if (!save) throw new Error('Draft: no save function was given');
		await this.action.run(async () => {
			const answer = await save(this.#clone(this.value));
			this.load(answer ?? this.value, true);
		});
		return !this.action.error;
	};
}

/**
 * One draft per key (a camera, a person, a stream): each with its own Save and Undo, and one question when the page
 * is left with any of them edited.
 */
export class Drafts<T> {
	#items = $state<Record<string, Draft<T>>>({});
	readonly #make: (key: string) => Draft<T>;

	/** `make` builds the draft for a key (give it `guard: false`; this asks once for all). */
	constructor(make: (key: string) => Draft<T>, options: { guard?: boolean } = {}) {
		this.#make = make;
		if (options.guard !== false) guardUnsaved(() => this.dirty);
	}

	/** The draft of a key, made on first use. */
	of = (key: string): Draft<T> => (this.#items[key] ??= this.#make(key));

	/** Any draft has unsaved edits. */
	get dirty(): boolean {
		return Object.values(this.#items).some((d) => d.dirty);
	}

	/** Is this key's draft edited? (Without making it.) */
	isDirty = (key: string): boolean => !!this.#items[key]?.dirty;

	/** Drop a draft (its thing is gone). */
	forget = (key: string) => {
		delete this.#items[key];
	};
}
