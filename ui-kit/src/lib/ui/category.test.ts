import { describe, expect, it } from 'vitest';
import { CAT, CATEGORY_COUNT, categoryOf } from './category';

describe('category colours', () => {
	it('gives a name the same colour every time, one of the eight', () => {
		const n = categoryOf('kitchen');
		expect(categoryOf('kitchen')).toBe(n);
		expect(n).toBeGreaterThanOrEqual(1);
		expect(n).toBeLessThanOrEqual(CATEGORY_COUNT);
	});

	it('spreads names over the colours', () => {
		const seen = new Set(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l'].map(categoryOf));
		expect(seen.size).toBeGreaterThan(4);
	});

	it('has class names for every colour', () => {
		for (let n = 1; n <= CATEGORY_COUNT; n++) expect(CAT.chip[n]).toContain(`text-cat-${n}`);
	});
});
