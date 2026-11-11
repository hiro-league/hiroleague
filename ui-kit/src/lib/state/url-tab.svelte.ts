// The open tab of a page, in the address (?tab=...): a tab can be linked to, and Back returns to
// the tab before. The last tab is also remembered in this browser, for a plain visit to the page.
import { goto } from '$app/navigation';
import { page } from '$app/state';
import { load, save } from '$kit/state/persist';
import type { PrefKey } from '$hiro-app/prefs';

export class UrlTab<T extends string> {
	#remembered: T;

	/** `pref`: where the last tab is remembered; `tabs`: the page's tabs; `fallback`: the first visit's. */
	constructor(
		private pref: PrefKey,
		private tabs: readonly T[],
		fallback: T
	) {
		this.#remembered = $state(load(pref, fallback, (v) => tabs.includes(v as T)));
	}

	get current(): T {
		const v = page.url.searchParams.get('tab') as T | null;
		return v && this.tabs.includes(v) ? v : this.#remembered;
	}

	set current(tab: T) {
		if (tab === this.current) return;
		this.#remembered = tab;
		save(this.pref, tab);
		const url = new URL(page.url);
		url.searchParams.set('tab', tab);
		void goto(url, { keepFocus: true, noScroll: true });
	}
}

/** A link to a page's tab, e.g. `tabLink(resolve('/settings'), 'frigate')`. */
export const tabLink = (path: string, tab: string) => `${path}?tab=${encodeURIComponent(tab)}`;
