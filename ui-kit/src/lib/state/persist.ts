// Per-browser UI preferences (filters, grouping, sort, open/closed sections) in localStorage.
// Storage can be unavailable (private windows, blocked site data), so every access is guarded and
// the page falls back to its defaults.

// UI kit, step 1: the prefix and the keys are the app's own (lib/app), so this file is the same in every Hiro app.
import { APP } from '$hiro-app/app';
import type { PrefKey } from '$hiro-app/prefs';

const PREFIX = APP.storagePrefix;

export function load<T>(key: PrefKey, fallback: T, valid: (v: unknown) => boolean = () => true): T {
	try {
		const raw = localStorage.getItem(PREFIX + key);
		if (raw === null) return fallback;
		const value = JSON.parse(raw);
		return valid(value) ? (value as T) : fallback;
	} catch {
		return fallback;
	}
}

export function save(key: PrefKey, value: unknown): void {
	try {
		localStorage.setItem(PREFIX + key, JSON.stringify(value));
	} catch {
		// not saved; the setting still works for this visit
	}
}

export const isRecord = (v: unknown): v is Record<string, boolean> =>
	typeof v === 'object' && v !== null && !Array.isArray(v);
