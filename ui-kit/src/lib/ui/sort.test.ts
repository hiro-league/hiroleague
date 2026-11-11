import { describe, expect, it } from 'vitest';
import { compare, Sorter } from './sort.svelte';

describe('compare', () => {
	it('orders IP addresses by their numbers, not as text', () => {
		const ips = ['192.168.1.100', '192.168.1.11', '192.168.1.2'];
		expect(ips.toSorted(compare)).toEqual(['192.168.1.2', '192.168.1.11', '192.168.1.100']);
	});

	it('orders text with numbers in it naturally, ignoring case', () => {
		expect(['cam10', 'Cam2', 'cam1'].toSorted(compare)).toEqual(['cam1', 'Cam2', 'cam10']);
	});
});

describe('Sorter', () => {
	type Row = { name: string; ip: string | null };
	const rows: Row[] = [
		{ name: 'TV', ip: '192.168.1.20' },
		{ name: 'lamp', ip: null },
		{ name: 'Camera', ip: '192.168.1.3' }
	];
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
