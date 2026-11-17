import { describe, expect, it } from 'vitest';
import { commandFilter, searched } from './pick';

const STREAMS = [
	{ value: 'state:front_door|cam3', label: 'cam3 Door state' },
	{ value: 'state:bedroom_light|cam1', label: 'cam1 Master bedroom light' },
	{ value: 'room|mark|cam3', label: 'Room Presence: Mark in Door Cam' }
];

describe('a dropdown search', () => {
	it('keeps the choices that have every word typed, in any order and case', () => {
		expect(searched(STREAMS, '').map((o) => o.value)).toEqual(STREAMS.map((o) => o.value));
		expect(searched(STREAMS, 'DOOR').map((o) => o.label)).toEqual(['cam3 Door state', 'Room Presence: Mark in Door Cam']);
		expect(searched(STREAMS, 'state door').map((o) => o.label)).toEqual(['cam3 Door state']);
		expect(searched(STREAMS, '  light   cam1 ').map((o) => o.label)).toEqual(['cam1 Master bedroom light']);
		expect(searched(STREAMS, 'garage')).toEqual([]);
	});

	it('also finds a choice by its id', () => {
		expect(searched(STREAMS, 'front_door').map((o) => o.label)).toEqual(['cam3 Door state']);
	});

	it("gives Command's list the same rule, over the value and the label", () => {
		expect(commandFilter('state:front_door|cam3', 'door STATE', ['cam3 Door state'])).toBe(1);
		expect(commandFilter('room|mark|cam3', 'mark presence', ['Room Presence: Mark in Door Cam'])).toBe(1);
		expect(commandFilter('room|mark|cam3', 'garage', ['Room Presence: Mark in Door Cam'])).toBe(0);
		expect(commandFilter('anything', '')).toBe(1);
	});
});
