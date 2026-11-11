// Click-to-sort for tables: click a column once for ascending, again for descending (and, for a table that wants it,
// a third time for "no sorting"). Empty values always sort last, whatever the direction.
//
// Two pieces: `SortState` is only the choice (which column, which way, kept in the address bar when asked), for a page
// whose rows are ordered by its own code; `Sorter` adds the columns' values and orders the rows itself.
// UI kit, step 7: one set, from the apps' Sorter and the HiroLeague admin's table sort (three-state, address bar,
// allowed columns, aria-sort).

export type SortValue = string | number | boolean | null | undefined;
export type SortDirection = 'asc' | 'desc';
export type SortOrder = SortDirection | 'none';
export type AriaSort = 'ascending' | 'descending' | 'none';

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

// "none" counts as ascending where a direction is required (a sort function that has no "off")
export function asSortDirection(order: SortOrder): SortDirection {
	return order === 'none' ? 'asc' : order;
}

export type SortStateOptions<K extends string> = {
	initial?: K | null; // the column the table starts on (none: unsorted)
	order?: SortOrder; // the way it starts (default ascending)
	allowed?: readonly K[]; // columns the address bar may name
	threeState?: boolean; // a third click on the same column turns the sorting off
	url?: boolean | { sortParam?: string; orderParam?: string }; // keep the choice in the address bar
};

export class SortState<K extends string = string> {
	key = $state<K | null>(null);
	desc = $state(false);
	off = $state(false); // three-state tables: the column is picked but the sorting is off

	private threeState: boolean;
	private urlParams: { sortParam: string; orderParam: string } | null = null;

	constructor(options: SortStateOptions<K> = {}) {
		const { allowed, url } = options;
		this.threeState = options.threeState ?? false;
		this.set(options.initial ?? null, options.order ?? 'asc', false);

		if (!url || typeof window === 'undefined') return;
		const sortParam = (typeof url === 'object' && url.sortParam) || 'sort';
		const orderParam = (typeof url === 'object' && url.orderParam) || 'sort_dir';
		this.urlParams = { sortParam, orderParam };
		const startKey = options.initial ?? null;
		const startOrder = options.order ?? 'asc';
		const reread = () => {
			const params = new URL(window.location.href).searchParams;
			const rawKey = params.get(sortParam);
			const rawOrder = params.get(orderParam);
			const key = rawKey && (!allowed || (allowed as readonly string[]).includes(rawKey)) ? (rawKey as K) : startKey;
			const order = rawOrder === 'asc' || rawOrder === 'desc' || rawOrder === 'none' ? rawOrder : startOrder;
			this.set(key, order, false);
		};
		reread();
		// back/forward keeps the choice and the address bar together (we only replaceState on a click)
		$effect(() => {
			window.addEventListener('popstate', reread);
			return () => window.removeEventListener('popstate', reread);
		});
	}

	get direction(): SortOrder {
		return this.off ? 'none' : this.desc ? 'desc' : 'asc';
	}

	ariaSort(key: string): AriaSort {
		if (this.key !== key || this.off) return 'none';
		return this.desc ? 'descending' : 'ascending';
	}

	set(key: K | null, order: SortOrder, writeUrl = true) {
		this.key = key;
		this.off = order === 'none';
		this.desc = order === 'desc';
		if (writeUrl && this.urlParams && key !== null && typeof window !== 'undefined') {
			const url = new URL(window.location.href);
			url.searchParams.set(this.urlParams.sortParam, key);
			url.searchParams.set(this.urlParams.orderParam, order);
			window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
		}
	}

	toggle(key: K) {
		if (this.key !== key) this.set(key, 'asc');
		else if (this.off) this.set(key, 'asc');
		else if (!this.desc) this.set(key, 'desc');
		else this.set(key, this.threeState ? 'none' : 'asc');
	}
}

export class Sorter<T> extends SortState {
	constructor(
		private columns: Record<string, (row: T) => SortValue>,
		initial: string | null = null,
		options: Omit<SortStateOptions<string>, 'initial'> = {}
	) {
		super({ allowed: Object.keys(columns), ...options, initial });
	}

	has(key: string) {
		return key in this.columns;
	}

	apply(rows: T[]): T[] {
		const get = this.key && !this.off ? this.columns[this.key] : null;
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
