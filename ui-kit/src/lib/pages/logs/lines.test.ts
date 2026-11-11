import { describe, expect, it } from 'vitest';
import type { LogLine } from './api';
import { areaOf, group } from './lines';

const line = (id: string, at: string, message: string, logger = 'sample.gallery'): LogLine => ({
	id,
	at,
	level: 'WARNING',
	logger,
	source: 'sample',
	message,
	detail: null
});

describe('areaOf', () => {
	it('names the area of a logger, or keeps the name', () => {
		expect(areaOf('sample.gallery')).toBe('Gallery');
		expect(areaOf('sample.gallery.progress')).toBe('Gallery');
		expect(areaOf('sample.app')).toBe('Web server');
		expect(areaOf('sample.gallerydware')).toBe('sample.gallerydware'); // a prefix only counts at a dot
	});
});

describe('group', () => {
	it('shows lines that differ only in numbers once, the latest first', () => {
		const groups = group([
			line('a:3', '2026-09-29T10:03:00Z', 'HA connection lost; retrying in 10 s'),
			line('a:2', '2026-09-29T10:02:00Z', 'Frigate: /api/events was slow: 8.1 s'),
			line('a:1', '2026-09-29T10:01:00Z', 'HA connection lost; retrying in 5 s')
		]);
		expect(groups.map((g) => [g.line.id, g.count])).toEqual([
			['a:3', 2],
			['a:2', 1]
		]);
		expect(groups[0].first).toBe('2026-09-29T10:01:00Z');
		expect(groups[0].last).toBe('2026-09-29T10:03:00Z');
	});

	it('keeps apart the same words from different loggers', () => {
		expect(group([line('a', 't2', 'failed', 'sample.gallery'), line('b', 't1', 'failed', 'sample.app')])).toHaveLength(2);
	});
});
