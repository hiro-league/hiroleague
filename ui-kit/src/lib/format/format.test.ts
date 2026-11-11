import { describe, expect, it } from 'vitest';
import { ago, agoSeconds, agoShort, clock, dateTime, fullDateTime, hourLabel, shortDate } from '$kit/format/time';
import { firstName } from './names';
import { usd } from './money';

const NOW = Date.parse('2026-09-28T12:00:00Z');
const before = (s: number) => new Date(NOW - s * 1000).toISOString();

describe('ago', () => {
	it('says just now, minutes, hours, then days', () => {
		expect(ago(before(20), NOW)).toBe('just now');
		expect(ago(before(5 * 60), NOW)).toBe('5 min ago');
		expect(ago(before(3 * 3600), NOW)).toBe('3 h ago');
		expect(ago(before(47 * 3600), NOW)).toBe('47 h ago');
		expect(ago(before(3 * 86400), NOW)).toBe('3 days ago');
	});
	it('treats a time in the future as now', () => expect(ago(before(-600), NOW)).toBe('just now'));
});

describe('agoSeconds', () => {
	it('counts seconds under a minute', () => {
		expect(agoSeconds(before(12), NOW)).toBe('12 s ago');
		expect(agoSeconds(before(80 * 60), NOW)).toBe('80 min ago');
		expect(agoSeconds(before(2 * 3600), NOW)).toBe('2 h ago');
	});
	it('says nothing without a time', () => expect(agoSeconds(null, NOW)).toBe(''));
});

describe('agoShort', () => {
	it('takes ISO times and epoch seconds', () => {
		expect(agoShort(before(10), NOW)).toBe('just now');
		expect(agoShort((NOW - 5 * 60_000) / 1000, NOW)).toBe('5 min');
		expect(agoShort(before(2 * 3600), NOW)).toBe('2 h');
	});
	it('gives the date after a day', () => expect(agoShort(before(3 * 86400), NOW)).not.toMatch(/h$|min$/));
});

describe('names and money', () => {
	it('firstName', () => {
		expect(firstName('Michel Habib')).toBe('Michel');
		expect(firstName('TMona')).toBe('TMona');
	});
	it('usd', () => {
		expect(usd(null)).toBe('$?');
		expect(usd(0)).toBe('$0');
		expect(usd(0.0011)).toBe('$0.0011');
		expect(usd(0.042)).toBe('$0.042');
		expect(usd(1.2)).toBe('$1.20');
	});
});

describe('dates and times (12-hour, always with the day)', () => {
	// Local times: the helpers use the browser's time zone.
	const now = new Date(2026, 8, 29, 13, 20); // Tue, Sep 29 2026, 1:20 PM
	it('clock is 12-hour with AM/PM', () => {
		expect(clock(new Date(2026, 8, 29, 13, 15, 46), true)).toBe('1:15:46 PM');
		expect(clock(new Date(2026, 8, 29, 0, 5))).toBe('12:05 AM');
		expect(clock(new Date(2026, 8, 29, 12, 0))).toBe('12:00 PM');
		expect(hourLabel(new Date(2026, 8, 29, 15))).toBe('3 PM');
	});
	it('dateTime always says the day', () => {
		expect(dateTime(new Date(2026, 8, 29, 9, 5), { now })).toBe('Today, 9:05 AM');
		expect(dateTime(new Date(2026, 8, 28, 23, 57), { now })).toBe('Yesterday, 11:57 PM');
		expect(dateTime(new Date(2026, 8, 24, 8, 0), { now })).toBe('Thu, Sep 24, 8:00 AM');
		expect(dateTime(new Date(2025, 11, 27, 9, 5), { now })).toBe('Sat, Dec 27, 2025, 9:05 AM');
	});
	it('full and short dates', () => {
		expect(fullDateTime(new Date(2026, 8, 28, 23, 57, 3))).toBe('Mon, Sep 28, 2026, 11:57:03 PM');
		expect(shortDate(new Date(2026, 8, 28), false, now)).toBe('Sep 28');
		expect(shortDate(new Date(2026, 8, 28), true, now)).toBe('Sep 28, 2026');
	});
});
