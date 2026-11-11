// A dropdown's choices and its search (PickSelect). Pure, tested next to it.

export type PickOption = { value: string; label: string };

/** A list this long gets a search box: shorter ones are read at a glance. */
export const SEARCH_FROM = 9;

/** The choices a search leaves: every word typed is in the label (or the value), in any order, any case. */
export function searched<T extends PickOption>(options: readonly T[], query: string): T[] {
	const words = query.toLowerCase().split(/\s+/).filter(Boolean);
	if (!words.length) return [...options];
	return options.filter((o) => {
		const text = `${o.label} ${o.value}`.toLowerCase();
		return words.every((w) => text.includes(w));
	});
}

/** The choice the arrow keys go to next from `at` (-1: none yet), staying inside the list. */
export const stepped = (at: number, by: 1 | -1, count: number) => (count ? Math.min(Math.max(at + by, 0), count - 1) : -1);
