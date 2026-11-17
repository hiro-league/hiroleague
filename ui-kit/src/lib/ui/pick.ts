// A dropdown's choices and its search (PickSelect). Pure, tested next to it.

// UI kit, step 3: `disabled` and `title` per choice. A choice may have the empty value ("All", "None", "Default").
export type PickOption = { value: string; label: string; disabled?: boolean; title?: string };

/** A list this long gets a search box: shorter ones are read at a glance. */
export const SEARCH_FROM = 9;

/** Whether `text` has every word of `query`, in any order, any case (an empty query matches everything). */
export function matches(text: string, query: string): boolean {
	const words = query.toLowerCase().split(/\s+/).filter(Boolean);
	const lower = text.toLowerCase();
	return words.every((w) => lower.includes(w));
}

/** The choices a search leaves: every word typed is in the label (or the value), in any order, any case. */
export function searched<T extends PickOption>(options: readonly T[], query: string): T[] {
	return options.filter((o) => matches(`${o.label} ${o.value}`, query));
}

/** Command's filter for PickSelect's long list (UI kit, step 7c): the same rule as `searched`, over an item's value
 *  and its keywords (the label). Command keeps the items scoring above 0. */
export const commandFilter = (value: string, search: string, keywords: string[] = []) =>
	matches(`${keywords.join(' ')} ${value}`, search) ? 1 : 0;
