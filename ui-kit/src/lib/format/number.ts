// Numbers as the pages show them, the same in every Hiro app and whatever the browser's language: thousands with a
// comma, a dot for decimals ("12,480", "3.5"). `toLocaleString()` follows the computer's settings and differed between
// machines. UI kit, step 5.

const grouped = new Intl.NumberFormat('en-US');

/** A whole count: "12,480". Null or not a number: "–". */
export function count(n: number | null | undefined): string {
	return n == null || !Number.isFinite(n) ? '–' : grouped.format(Math.round(n));
}

/** A number with up to `digits` decimals, trailing zeros dropped: "3.5", "1,204.25", "7". */
export function decimal(n: number | null | undefined, digits = 1): string {
	if (n == null || !Number.isFinite(n)) return '–';
	return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(n);
}

/** A share (0 … 1) as a percent: "42%", "3.5%" with `digits`. */
export function percent(share: number | null | undefined, digits = 0): string {
	return share == null || !Number.isFinite(share) ? '–' : `${decimal(share * 100, digits)}%`;
}

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const;

/** A size in bytes, in the largest unit that keeps it 1 or more (1,000 a step, as disks are sold): "1.2 GB", "640 KB". */
export function bytes(n: number | null | undefined, digits = 1): string {
	if (n == null || !Number.isFinite(n)) return '–';
	let v = Math.abs(n);
	let u = 0;
	while (v >= 1000 && u < UNITS.length - 1) {
		v /= 1000;
		u++;
	}
	return `${n < 0 ? '-' : ''}${decimal(v, u === 0 ? 0 : digits)} ${UNITS[u]}`;
}

/** "1 person", "3 people": a count with the right word. */
export function plural(n: number, one: string, many: string = `${one}s`): string {
	return `${count(n)} ${n === 1 ? one : many}`;
}
