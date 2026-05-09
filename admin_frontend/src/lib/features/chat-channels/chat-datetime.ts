/**
 * Chat admin timestamps: browser-local calendar, friendly copy (weekday via en-US).
 * "Today" when the instant falls on today's local date.
 */

function startOfLocalDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function isSameLocalDay(a: Date, b: Date): boolean {
  return startOfLocalDay(a).getTime() === startOfLocalDay(b).getTime();
}

const weekdayShort = new Intl.DateTimeFormat('en-US', { weekday: 'short' });
const dateMedium = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric'
});
const timeWithSeconds12h = new Intl.DateTimeFormat(undefined, {
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  hour12: true
});

/** Two spaces between date label and clock per admin chat UX preference. */
const DATE_TIME_GAP = '  ';

export function formatChatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';

  const now = new Date();
  const wk = weekdayShort.format(d);
  const cal = dateMedium.format(d);
  const datePart = isSameLocalDay(d, now) ? 'Today' : `${wk}, ${cal}`;
  const timePart = timeWithSeconds12h.format(d);
  return `${datePart}${DATE_TIME_GAP}${timePart}`;
}
