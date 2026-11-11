import { describe, expect, it } from 'vitest';
import { clampWidth, isWidth, SIDEBAR_DEFAULT, SIDEBAR_MAX, SIDEBAR_MIN } from './sidebar-width';

describe('sidebar width', () => {
	it('keeps a dragged width between the narrowest and the widest, in whole pixels', () => {
		expect(clampWidth(300.6)).toBe(301);
		expect(clampWidth(10)).toBe(SIDEBAR_MIN);
		expect(clampWidth(5000)).toBe(SIDEBAR_MAX);
	});

	it('takes a saved width only when the menu can use it as it is', () => {
		expect(isWidth(SIDEBAR_DEFAULT)).toBe(true);
		expect(isWidth(SIDEBAR_MAX + 1)).toBe(false);
		expect(isWidth(300.5)).toBe(false);
		expect(isWidth('300')).toBe(false);
		expect(isWidth(Number.NaN)).toBe(false);
	});
});
