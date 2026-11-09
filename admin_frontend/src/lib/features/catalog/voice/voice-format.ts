/**
 * Voices (Phase 7b): small helpers the voice pages share — where a voice is from, a language's name,
 * how long Google keeps a designed voice, a clip's price, and putting a sound tag at the cursor.
 * People read these: dates say the day (and the year only when it isn't this year).
 */
import type { VoiceSource } from '$lib/api/voice';

/** studio ("kore"), library ("ar-eg-advisor-11") or mine ("voice_…"), from the voice id's shape. */
export const sourceOf = (id: string): VoiceSource => (id.startsWith('voice_') ? 'mine' : id.includes('-') ? 'library' : 'studio');

const names = (() => {
  try {
    return new Intl.DisplayNames(['en'], { type: 'language' });
  } catch {
    return null;
  }
})();

/** "ar-EG" → "Arabic (Egypt)" (the code itself when the browser can't name it). */
export function langName(code: string): string {
  try {
    return names?.of(code) ?? code;
  } catch {
    return code;
  }
}

const WEEKDAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** How long Google keeps a designed voice: "expires in 41 days", "kept until Sat, Oct 2, 2027". */
export function keptUntil(iso: string | null, now = new Date()): string {
  if (!iso) return '';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  const days = Math.ceil((at.getTime() - now.getTime()) / 86_400_000);
  if (days <= 0) return 'expired';
  if (days <= 60) return `expires in ${days} day${days === 1 ? '' : 's'}`;
  const year = at.getFullYear() !== now.getFullYear() ? `, ${at.getFullYear()}` : '';
  return `kept until ${WEEKDAY[at.getDay()]}, ${MONTH[at.getMonth()]} ${at.getDate()}${year}`;
}

/** A price: under a cent with four decimals; "≈" when estimated (OpenAI reports no usage); "no price". */
export const money = (usd: number | null, exact = true) =>
  usd === null ? 'no price' : `${exact ? '' : '≈'}$${usd < 0.01 ? usd.toFixed(4) : usd.toFixed(3)}`;

export const hasTags = (text: string) => /<[a-z -]+>/i.test(text);

/** Put "<tag>" at the cursor (or over a selection), a space each side unless one is there. */
export function withTag(text: string, start: number, end: number, tag: string): { text: string; at: number } {
  const before = text.slice(0, start);
  const after = text.slice(end);
  const piece = `${before && !before.endsWith(' ') ? ' ' : ''}<${tag}>${after.startsWith(' ') ? '' : ' '}`;
  return { text: before + piece + after, at: before.length + piece.length };
}
