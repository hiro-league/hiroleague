// The category colours: eight hues for things sorted into kinds (a service's category, a log's source, a chip that
// says what sort of thing a row is), told apart at a glance and readable on the page in light and dark. The theme
// holds them (--cat-1 … --cat-8); here are the class names, written out whole so Tailwind finds them.
// A fixed kind takes its number (`CAT.text[3]`); a kind the app does not know ahead (a name typed by someone) gets
// one from its name with `categoryOf`, the same one every time.
// Not for status (use success / warning / destructive) and not for colours that carry data (a lamp's own colour,
// a chart's scale): those stay as they are.
// UI kit, step 3.

export const CATEGORY_COUNT = 8;

/** 1 … 8 for a name: the same name always gets the same colour. */
export function categoryOf(key: string): number {
	let h = 0;
	for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
	return (h % CATEGORY_COUNT) + 1;
}

type Row = Record<number, string>;

/** Class names per category number (1 … 8). */
export const CAT: { text: Row; bg: Row; soft: Row; border: Row; dot: Row; chip: Row } = {
	/** the words in the colour */
	text: { 1: 'text-cat-1', 2: 'text-cat-2', 3: 'text-cat-3', 4: 'text-cat-4', 5: 'text-cat-5', 6: 'text-cat-6', 7: 'text-cat-7', 8: 'text-cat-8' },
	/** a solid fill (a bar, a swatch) */
	bg: { 1: 'bg-cat-1', 2: 'bg-cat-2', 3: 'bg-cat-3', 4: 'bg-cat-4', 5: 'bg-cat-5', 6: 'bg-cat-6', 7: 'bg-cat-7', 8: 'bg-cat-8' },
	/** a faint fill behind words */
	soft: { 1: 'bg-cat-1/12', 2: 'bg-cat-2/12', 3: 'bg-cat-3/12', 4: 'bg-cat-4/12', 5: 'bg-cat-5/12', 6: 'bg-cat-6/12', 7: 'bg-cat-7/12', 8: 'bg-cat-8/12' },
	border: { 1: 'border-cat-1/40', 2: 'border-cat-2/40', 3: 'border-cat-3/40', 4: 'border-cat-4/40', 5: 'border-cat-5/40', 6: 'border-cat-6/40', 7: 'border-cat-7/40', 8: 'border-cat-8/40' },
	dot: { 1: 'bg-cat-1', 2: 'bg-cat-2', 3: 'bg-cat-3', 4: 'bg-cat-4', 5: 'bg-cat-5', 6: 'bg-cat-6', 7: 'bg-cat-7', 8: 'bg-cat-8' },
	/** a chip: faint fill, the words and a thin border in the colour */
	chip: {
		1: 'border-cat-1/40 bg-cat-1/12 text-cat-1',
		2: 'border-cat-2/40 bg-cat-2/12 text-cat-2',
		3: 'border-cat-3/40 bg-cat-3/12 text-cat-3',
		4: 'border-cat-4/40 bg-cat-4/12 text-cat-4',
		5: 'border-cat-5/40 bg-cat-5/12 text-cat-5',
		6: 'border-cat-6/40 bg-cat-6/12 text-cat-6',
		7: 'border-cat-7/40 bg-cat-7/12 text-cat-7',
		8: 'border-cat-8/40 bg-cat-8/12 text-cat-8'
	}
};

/** The CSS colour of a category, for SVG and canvas (fill, stroke). */
export const catVar = (n: number) => `var(--cat-${n})`;
