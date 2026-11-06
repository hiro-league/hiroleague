/**
 * Moments for people: "Today, 1:15 PM", "Yesterday, 11:57 PM", "Mon, Sep 28, 9:05 AM",
 * and the year only when it isn't this year ("Sat, Dec 27, 2025, 9:05 AM").
 *
 * 12-hour clock, always with the day. Spelled out by hand (not Intl / toLocale*) so a
 * 24-hour browser locale can't change it. Same rules as the server's
 * `hiro_commons.timestamps.human_datetime`. Shown in the browser's time zone.
 */

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function clock12h(d: Date): string {
  const hour = d.getHours() % 12 || 12;
  const suffix = d.getHours() < 12 ? 'AM' : 'PM';
  return `${hour}:${String(d.getMinutes()).padStart(2, '0')} ${suffix}`;
}

function dayNumber(d: Date): number {
  return Math.floor(new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 86_400_000);
}

/** Format an ISO string or Date; `—` for null, empty or unparseable values. */
export function humanDateTime(value: string | Date | null | undefined, now: Date = new Date()): string {
  if (!value) return '—';
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  const clock = clock12h(d);
  const daysAgo = dayNumber(now) - dayNumber(d);
  if (daysAgo === 0) return `Today, ${clock}`;
  if (daysAgo === 1) return `Yesterday, ${clock}`;
  const year = d.getFullYear() !== now.getFullYear() ? `, ${d.getFullYear()}` : '';
  return `${WEEKDAYS[d.getDay()]}, ${MONTHS[d.getMonth()]} ${d.getDate()}${year}, ${clock}`;
}
