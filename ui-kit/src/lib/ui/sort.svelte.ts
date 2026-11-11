// Click-to-sort for tables: click a column once for ascending, again for descending.
// Empty values always sort last, whatever the direction.

export type SortValue = string | number | boolean | null | undefined;

const ipKey = (ip: string) =>
	ip
		.split('.')
		.map((n) => n.padStart(3, '0'))
		.join('.');

export function compare(a: SortValue, b: SortValue): number {
	if (typeof a === 'string' && typeof b === 'string') {
		if (/^\d+\.\d+\.\d+\.\d+$/.test(a) && /^\d+\.\d+\.\d+\.\d+$/.test(b)) return ipKey(a).localeCompare(ipKey(b));
		return a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });
	}
	return Number(a) - Number(b);
}

export class Sorter<T> {
	key = $state<string | null>(null);
	desc = $state(false);

	constructor(
		private columns: Record<string, (row: T) => SortValue>,
		initial: string | null = null
	) {
		this.key = initial;
	}

	has(key: string) {
		return key in this.columns;
	}

	toggle(key: string) {
		if (this.key === key) this.desc = !this.desc;
		else {
			this.key = key;
			this.desc = false;
		}
	}

	apply(rows: T[]): T[] {
		const get = this.key ? this.columns[this.key] : null;
		if (!get) return rows;
		const empty = (v: SortValue) => v === null || v === undefined || v === '';
		return rows.toSorted((x, y) => {
			const a = get(x);
			const b = get(y);
			if (empty(a) || empty(b)) return Number(empty(a)) - Number(empty(b));
			return this.desc ? compare(b, a) : compare(a, b);
		});
	}
}
