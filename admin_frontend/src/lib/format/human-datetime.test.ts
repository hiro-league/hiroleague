import { describe, expect, it } from 'vitest';
import { humanDateTime } from './human-datetime';

// Local-time Dates so the test doesn't depend on the machine's time zone.
const now = new Date(2026, 10, 6, 15, 0); // Fri, Nov 6, 2026, 3:00 PM

describe('humanDateTime', () => {
  it('says Today with a 12-hour clock', () => {
    expect(humanDateTime(new Date(2026, 10, 6, 13, 15), now)).toBe('Today, 1:15 PM');
    expect(humanDateTime(new Date(2026, 10, 6, 0, 5), now)).toBe('Today, 12:05 AM');
  });

  it('says Yesterday', () => {
    expect(humanDateTime(new Date(2026, 10, 5, 23, 57), now)).toBe('Yesterday, 11:57 PM');
  });

  it('names the day and month, with the year only when it is not this year', () => {
    expect(humanDateTime(new Date(2026, 8, 28, 9, 5), now)).toBe('Mon, Sep 28, 9:05 AM');
    expect(humanDateTime(new Date(2025, 11, 27, 9, 5), now)).toBe('Sat, Dec 27, 2025, 9:05 AM');
  });

  it('shows a dash for nothing or garbage', () => {
    expect(humanDateTime(null, now)).toBe('—');
    expect(humanDateTime('not a date', now)).toBe('—');
  });
});
