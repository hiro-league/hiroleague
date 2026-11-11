import { describe, expect, it } from 'vitest';
import { oneLine, pretty, shape } from './shape';

const schema = {
	type: 'object',
	properties: {
		people: {
			type: 'array',
			items: { type: 'object', properties: { name: { type: 'string', enum: ['Joe', 'unknown'] }, line: { type: 'string', maxLength: 120 } } }
		},
		light: { type: 'string', enum: ['on', 'off'], description: 'on = a lamp is lit' },
		count: { type: 'integer', minimum: 0, maximum: 9 }
	}
};

describe('LLM requests: any schema and reply', () => {
	it('says the shape in words, nested parts indented', () => {
		expect(shape(schema)).toEqual([
			{ path: 'people', depth: 0, allowed: 'a list; each item has:' },
			{ path: 'name', depth: 1, allowed: 'one of: Joe, unknown' },
			{ path: 'line', depth: 1, allowed: 'text, up to 120 characters' },
			{ path: 'light', depth: 0, allowed: 'one of: on, off (on = a lamp is lit)' },
			{ path: 'count', depth: 0, allowed: 'a number 0–9' }
		]);
		expect(shape(undefined)).toEqual([]);
	});

	it('lays out JSON replies and keeps anything else as it came', () => {
		expect(pretty('{"light":"off"}')).toBe('{\n  "light": "off"\n}');
		expect(pretty("I can't help with that.")).toBe("I can't help with that.");
		expect(pretty('"just a string"')).toBe('"just a string"');
	});

	it('sums a reply up in one line', () => {
		expect(oneLine('{"people":[{"name":"Joe","line":"at his desk"}],"light":"off"}')).toBe('people Joe · at his desk · light off');
		expect(oneLine('{"people":[]}')).toBe('people none');
		expect(oneLine('not JSON')).toBe('not JSON');
	});
});
