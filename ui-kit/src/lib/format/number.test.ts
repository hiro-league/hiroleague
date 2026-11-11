import { describe, expect, it } from 'vitest';
import { bytes, count, decimal, percent, plural } from './number';

describe('number formats', () => {
	it('writes counts with commas, whatever the browser', () => {
		expect(count(12480)).toBe('12,480');
		expect(count(3.6)).toBe('4');
		expect(count(null)).toBe('–');
		expect(count(Number.NaN)).toBe('–');
	});

	it('drops trailing zeros from decimals', () => {
		expect(decimal(3.5)).toBe('3.5');
		expect(decimal(7)).toBe('7');
		expect(decimal(1204.256, 2)).toBe('1,204.26');
	});

	it('writes shares as percents', () => {
		expect(percent(0.42)).toBe('42%');
		expect(percent(0.0351, 1)).toBe('3.5%');
		expect(percent(undefined)).toBe('–');
	});

	it('writes sizes in the largest unit', () => {
		expect(bytes(640)).toBe('640 B');
		expect(bytes(640_000)).toBe('640 KB');
		expect(bytes(1_234_000_000)).toBe('1.2 GB');
		expect(bytes(null)).toBe('–');
	});

	it('picks the word for one or many', () => {
		expect(plural(1, 'person', 'people')).toBe('1 person');
		expect(plural(3, 'person', 'people')).toBe('3 people');
		expect(plural(2, 'check')).toBe('2 checks');
	});
});
