// Times and dates, in words people read at a glance. One place, so every page says them the same way.
//
// The house format (CLAUDE.md, "Dates and times"): 12-hour clock with AM/PM, never 24-hour, and a time
// always says which day it is: "Today, 1:15 PM", "Yesterday, 11:57 PM", "Mon, Sep 28, 9:05 AM", and the
// year only when it isn't this one ("Sat, Dec 27, 2025, 9:05 AM"). Written out here, not left to the
// browser's locale, which can be 24-hour. Times are the browser's own (the home's) time zone.

type When = Date | string | number; // a Date, an ISO time, or epoch milliseconds

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const toDate = (t: When) => (t instanceof Date ? t : new Date(t));
const pad = (n: number) => String(n).padStart(2, '0');
const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

/** "1:15 PM"; with seconds, "1:15:46 PM". */
export function clock(t: When, seconds = false): string {
	const d = toDate(t);
	const h = d.getHours() % 12 || 12;
	return `${h}:${pad(d.getMinutes())}${seconds ? `:${pad(d.getSeconds())}` : ''} ${d.getHours() < 12 ? 'AM' : 'PM'}`;
}

/** An hour on an axis: "3 PM", "12 AM". */
export function hourLabel(t: When): string {
	const d = toDate(t);
	return `${d.getHours() % 12 || 12} ${d.getHours() < 12 ? 'AM' : 'PM'}`;
}

/** "Mon". */
export const weekday = (t: When) => DAYS[toDate(t).getDay()];

/** "Sep 28"; "Sep 28, 2025" in another year, or always with `year`. */
export function shortDate(t: When, year = false, now: When = Date.now()): string {
	const d = toDate(t);
	const y = year || d.getFullYear() !== toDate(now).getFullYear() ? `, ${d.getFullYear()}` : '';
	return `${MONTHS[d.getMonth()]} ${d.getDate()}${y}`;
}

/** Which day: "Today", "Yesterday", "Tomorrow", else "Mon, Sep 28" (with the year in another year). */
export function day(t: When, now: When = Date.now()): string {
	const d = toDate(t);
	const days = Math.round((midnight(toDate(now)) - midnight(d)) / 86_400_000);
	if (days === 0) return 'Today';
	if (days === 1) return 'Yesterday';
	if (days === -1) return 'Tomorrow';
	return `${weekday(d)}, ${shortDate(d, false, now)}`;
}

/** The day and the time: "Today, 1:15 PM", "Mon, Sep 28, 11:57 PM"; `seconds` adds them ("1:15:46 PM"). */
export function dateTime(t: When, opts: { seconds?: boolean; now?: When } = {}): string {
	return `${day(t, opts.now)}, ${clock(t, opts.seconds)}`;
}

/** Always the full date, for a tooltip: "Mon, Sep 28, 2026, 1:15:46 PM". */
export function fullDateTime(t: When): string {
	const d = toDate(t);
	return `${weekday(d)}, ${shortDate(d, true)}, ${clock(d, true)}`;
}

/** "just now", "5 min ago", "2 h ago", "3 days ago". */
export function ago(iso: string, now = Date.now()) {
	const min = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
	if (min < 1) return 'just now';
	if (min < 60) return `${min} min ago`;
	if (min < 48 * 60) return `${Math.round(min / 60)} h ago`;
	return `${Math.round(min / 1440)} days ago`;
}

/** Like `ago`, with seconds under a minute ("12 s ago"): for things that change every few seconds. */
export function agoSeconds(iso: string | null | undefined, now = Date.now()) {
	if (!iso) return '';
	const s = (now - new Date(iso).getTime()) / 1000;
	return s < 60 ? `${Math.max(0, Math.round(s))} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
}

/** Short, for tight spots: "just now", "5 min", "2 h", else the date. Takes an ISO time or epoch seconds. */
export function agoShort(t: string | number | null | undefined, now = Date.now()): string {
	if (t == null) return '';
	const ms = typeof t === 'number' ? t * 1000 : Date.parse(t);
	const s = (now - ms) / 1000;
	if (s < 60) return 'just now';
	if (s < 3600) return `${Math.round(s / 60)} min`;
	if (s < 86400) return `${Math.round(s / 3600)} h`;
	return shortDate(ms, false, now);
}

/** A time that may never have come: "never" for none. */
export const formatTime = (iso: string | null) => (iso ? dateTime(iso) : 'never');

/** The midnight starting a YYYY-MM-DD day (the home's day, not UTC's). */
export const dayOf = (s: string) => {
	const [y, m, d] = s.split('-').map(Number);
	return new Date(y, m - 1, d);
};
