// Amounts of money as the pages show them.

/** An estimated cost in USD: "$0.0011", "$0.042", "$1.20". */
export function usd(v: number | null | undefined): string {
	if (v == null) return '$?';
	if (v === 0) return '$0';
	return v < 0.01 ? `$${v.toPrecision(2)}` : v < 1 ? `$${v.toFixed(3)}` : `$${v.toFixed(2)}`;
}
