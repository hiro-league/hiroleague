// A preference kept in this browser (localStorage, via persist.ts): read once when made, written
// back whenever it changes. Make it while a component starts (it saves with an effect).
import { load, save } from '$kit/state/persist';
import type { PrefKey } from '$hiro-app/prefs';

export class Persisted<T> {
	current: T;

	constructor(key: PrefKey, fallback: T, valid: (v: unknown) => boolean = () => true) {
		this.current = $state(load(key, fallback, valid));
		$effect(() => save(key, $state.snapshot(this.current)));
	}
}

/** `persisted('sidebar.open', true, isBool).current` */
export const persisted = <T>(key: PrefKey, fallback: T, valid?: (v: unknown) => boolean) => new Persisted(key, fallback, valid);

export const isBool = (v: unknown): v is boolean => typeof v === 'boolean';
export const isString = (v: unknown): v is string => typeof v === 'string';
