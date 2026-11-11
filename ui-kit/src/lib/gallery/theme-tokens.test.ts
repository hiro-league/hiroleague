import { describe, expect, it } from 'vitest';
import { ALL_TOKENS, buildCss, emptyEdits, KIT, onlyChanges, parseTheme, resolveVars } from './theme-tokens';

describe('the kit values', () => {
	it('has a light and a dark value for every token', () => {
		for (const n of ALL_TOKENS) {
			expect(KIT.light[n], n).toBeTruthy();
			expect(KIT.dark[n], n).toBeTruthy();
		}
	});
});

describe('theme.css text', () => {
	it('writes only the edits, in :root and .dark blocks, and reads them back', () => {
		const e = emptyEdits();
		e.light.primary = '#112233';
		e.dark.primary = '#445566';
		e.dark.background = '#000000';
		const css = buildCss(e, Date.parse('2026-11-12T13:15:00'));
		expect(css).toContain(':root {\n\t--primary: #112233;\n}');
		expect(css).toContain('.dark {\n\t--background: #000000;\n\t--primary: #445566;\n}');
		expect(css).not.toContain('--card');
		expect(parseTheme(css)).toEqual(e);
	});
	it('writes no block for a mode with no edits', () => {
		const e = emptyEdits();
		e.light.ring = '#abcdef';
		expect(buildCss(e)).not.toContain('.dark');
	});
	it('drops loaded values that equal the kit and tokens it does not know', () => {
		const loaded = parseTheme(`:root { --primary: ${KIT.light.primary}; --ring: #123456; --nonsense: red; }`);
		expect(onlyChanges(loaded)).toEqual({ light: { ring: '#123456' }, dark: {} });
	});
});

describe('resolveVars', () => {
	it('follows var() through edits', () => {
		const e = emptyEdits();
		e.light['brand-blue'] = '#010203';
		expect(resolveVars('var(--brand-blue)', 'light', e)).toBe('#010203');
		expect(resolveVars('var(--chart-1)', 'light', e)).toBe('#010203');
	});
});
