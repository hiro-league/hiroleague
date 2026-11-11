// The Hiro theme's tokens as the Theme designer edits them: the list (grouped), the kit's own values (read from
// theme.css itself, so there is one source), and turning edits into an app's theme.css and back.
import kitCss from '$kit/theme.css?raw';
import { fullDateTime } from '$kit/format/time';

export type Mode = 'light' | 'dark';
export type Values = Record<string, string>;
/** What the designer keeps: only the tokens that differ from the kit, per mode. */
export type Edits = Record<Mode, Values>;

export const TOKEN_GROUPS: { title: string; tokens: string[] }[] = [
	{
		title: 'Surfaces and text',
		tokens: [
			'background', 'foreground', 'card', 'card-foreground', 'popover', 'popover-foreground', 'muted', 'muted-foreground',
			'accent', 'accent-foreground', 'secondary', 'secondary-foreground', 'border', 'input', 'ring'
		]
	},
	{ title: 'Primary', tokens: ['primary', 'primary-foreground'] },
	{ title: 'Status', tokens: ['success', 'warning', 'destructive'] },
	{ title: "The brand's colours", tokens: ['brand', 'brand-mid', 'brand-deep', 'brand-rose', 'brand-pink', 'brand-blue', 'brand-green'] },
	{ title: 'Charts', tokens: ['chart-1', 'chart-2', 'chart-3', 'chart-4', 'chart-5'] },
	{ title: 'Categories', tokens: Array.from({ length: 8 }, (_, i) => `cat-${i + 1}`) },
	{
		title: 'Menu (sidebar)',
		tokens: [
			'sidebar', 'sidebar-foreground', 'sidebar-primary', 'sidebar-primary-foreground', 'sidebar-accent',
			'sidebar-accent-foreground', 'sidebar-border', 'sidebar-ring'
		]
	}
];

export const ALL_TOKENS: string[] = TOKEN_GROUPS.flatMap((g) => g.tokens);
const KNOWN = new Set(ALL_TOKENS);

export const emptyEdits = (): Edits => ({ light: {}, dark: {} });

/** The `--name: value;` lines of `:root { }` and `.dark { }` blocks, for the tokens the designer knows. */
export function parseTheme(css: string): Edits {
	const out = emptyEdits();
	const text = css.replace(/\/\*[\s\S]*?\*\//g, '');
	for (const block of text.matchAll(/(:root|\.dark)\s*\{([^}]*)\}/g)) {
		const mode: Mode = block[1] === '.dark' ? 'dark' : 'light';
		for (const d of block[2].matchAll(/--([\w-]+)\s*:\s*([^;]+?)\s*(?:;|$)/g)) {
			if (KNOWN.has(d[1])) out[mode][d[1]] = d[2].trim();
		}
	}
	return out;
}

/** The kit's own values, from its theme.css. */
export const KIT: Edits = parseTheme(kitCss);

/** A value with its `var(--x)` replaced by what that token is in `mode` (edits over the kit's values). */
export function resolveVars(value: string, mode: Mode, edits: Edits, depth = 0): string {
	if (depth > 5) return value;
	return value.replace(/var\(--([\w-]+)\)/g, (whole, name: string) => {
		const inner = edits[mode][name] ?? KIT[mode][name];
		return inner === undefined ? whole : resolveVars(inner, mode, edits, depth + 1);
	});
}

/** What a token is now in `mode`. */
export const effective = (name: string, mode: Mode, edits: Edits): string => edits[mode][name] ?? KIT[mode][name] ?? '';

/** Only what differs from the kit, from text a person typed or pasted. */
export function onlyChanges(parsed: Edits): Edits {
	const out = emptyEdits();
	for (const mode of ['light', 'dark'] as const) {
		for (const [name, v] of Object.entries(parsed[mode])) if (v !== KIT[mode][name]) out[mode][name] = v;
	}
	return out;
}

export const countEdits = (e: Edits) => Object.keys(e.light).length + Object.keys(e.dark).length;

/** The text of an app's `src/lib/app/theme.css`: the tokens that differ from the kit, in token order. */
export function buildCss(edits: Edits, when: number = Date.now()): string {
	const lines = [
		`/* Made with the Theme designer (the admin's UI kit page), ${fullDateTime(when)}.`,
		`   Overrides of the kit's theme.css tokens; anything not listed is the Hiro palette as is. */`
	];
	for (const [selector, mode] of [[':root', 'light'], ['.dark', 'dark']] as const) {
		const decls = ALL_TOKENS.filter((n) => edits[mode][n] !== undefined).map((n) => `\t--${n}: ${edits[mode][n]};`);
		if (decls.length) lines.push(`${selector} {`, ...decls, '}');
	}
	return lines.join('\n') + '\n';
}

export const isEdits = (v: unknown): v is { edits: Edits; useEdits: boolean } => {
	if (typeof v !== 'object' || v === null) return false;
	const e = (v as { edits?: Record<string, unknown> }).edits;
	const rec = (r: unknown) => typeof r === 'object' && r !== null && Object.values(r).every((x) => typeof x === 'string');
	return !!e && rec(e.light) && rec(e.dark) && typeof (v as { useEdits?: unknown }).useEdits === 'boolean';
};
