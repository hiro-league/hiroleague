import { describe, expect, it } from 'vitest';
import { asSortDirection, compare, SortState, Sorter } from './sort.svelte';

describe('compare', () => {
	it('orders IP addresses by their numbers, not as text', () => {
		const ips = ['192.168.1.100', '192.168.1.11', '192.168.1.2'];
		expect(ips.toSorted(compare)).toEqual(['192.168.1.2', '192.168.1.11', '192.168.1.100']);
	});

	it('orders text with numbers in it naturally, ignoring case', () => {
		expect(['cam10', 'Cam2', 'cam1'].toSorted(compare)).toEqual(['cam1', 'Cam2', 'cam10']);
	});
});

type Row = { name: string; ip: string | null };
const rows: Row[] = [
	{ name: 'TV', ip: '192.168.1.20' },
	{ name: 'lamp', ip: null },
	{ name: 'Camera', ip: '192.168.1.3' }
];

describe('Sorter', () => {
	const sorter = () => new Sorter<Row>({ name: (r) => r.name, ip: (r) => r.ip });

	it('leaves the order alone until a column is picked', () => {
		expect(sorter().apply(rows)).toEqual(rows);
	});

	it('sorts up on the first click and down on the second', () => {
		const s = sorter();
		s.toggle('name');
		expect(s.apply(rows).map((r) => r.name)).toEqual(['Camera', 'lamp', 'TV']);
		s.toggle('name');
		expect(s.apply(rows).map((r) => r.name)).toEqual(['TV', 'lamp', 'Camera']);
	});

	it('keeps empty values last in both directions', () => {
		const s = sorter();
		s.toggle('ip');
		expect(s.apply(rows).map((r) => r.ip)).toEqual(['192.168.1.3', '192.168.1.20', null]);
		s.toggle('ip');
		expect(s.apply(rows).map((r) => r.ip)).toEqual(['192.168.1.20', '192.168.1.3', null]);
	});
});

describe('SortState', () => {
	it('selects ascending when switching to a new column', () => {
		const s = new SortState<string>({ initial: 'name', order: 'desc' });
		s.toggle('status');
		expect([s.key, s.direction]).toEqual(['status', 'asc']);
	});

	it('flips ascending and descending on the active column', () => {
		const s = new SortState({ initial: 'name' });
		s.toggle('name');
		expect(s.direction).toBe('desc');
		s.toggle('name');
		expect(s.direction).toBe('asc');
	});

	it('three-state goes ascending, descending, none, ascending on the same column', () => {
		const s = new SortState({ initial: 'name', threeState: true });
		s.toggle('name');
		expect(s.direction).toBe('desc');
		s.toggle('name');
		expect(s.direction).toBe('none');
		s.toggle('name');
		expect(s.direction).toBe('asc');
	});

	it('starts with the sorting off when asked, and the first click on its column is ascending', () => {
		const s = new SortState({ initial: 'time', order: 'none', threeState: true });
		expect(s.direction).toBe('none');
		s.toggle('time');
		expect(s.direction).toBe('asc');
	});

	it('says aria-sort for the active column only', () => {
		const s = new SortState<string>({ initial: 'name', order: 'desc' });
		expect(s.ariaSort('name')).toBe('descending');
		expect(s.ariaSort('status')).toBe('none');
		s.set('name', 'asc');
		expect(s.ariaSort('name')).toBe('ascending');
		s.set('name', 'none');
		expect(s.ariaSort('name')).toBe('none');
	});

	it('turns "none" into ascending where a direction is required', () => {
		expect(asSortDirection('none')).toBe('asc');
		expect(asSortDirection('desc')).toBe('desc');
	});

	it('a three-state Sorter leaves the rows alone while the sorting is off', () => {
		const s = new Sorter<Row>({ name: (r) => r.name }, 'name', { threeState: true });
		s.toggle('name'); // desc
		s.toggle('name'); // off
		expect(s.apply(rows)).toEqual(rows);
	});
});
