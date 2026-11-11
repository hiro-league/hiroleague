/**
 * Chat admin timestamps: the day and the time with seconds, in the browser's time zone. The words come
 * from the one formatter, `$lib/format/time` (UI kit step 1d), not from the browser's locale.
 */
import { clock, day } from '$lib/format/time';

/** Two spaces between date label and clock per admin chat UX preference. */
const DATE_TIME_GAP = '  ';

export function formatChatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${day(d)}${DATE_TIME_GAP}${clock(d, true)}`;
}
