/** Split plain text into matched / unmatched segments for safe {@html}-free highlighting. */
export function splitOnQuery(
  text: string | null | undefined,
  query: string
): { text: string; hit: boolean }[] {
  const value = text ?? '';
  const q = query.trim();
  if (!q || !value) return [{ text: value, hit: false }];
  const haystack = value.toLowerCase();
  const needle = q.toLowerCase();
  const out: { text: string; hit: boolean }[] = [];
  let i = 0;
  while (i < value.length) {
    const at = haystack.indexOf(needle, i);
    if (at === -1) {
      out.push({ text: value.slice(i), hit: false });
      break;
    }
    if (at > i) out.push({ text: value.slice(i, at), hit: false });
    out.push({ text: value.slice(at, at + needle.length), hit: true });
    i = at + needle.length;
  }
  return out;
}

/** Case-insensitive substring test; blank query never matches. */
export function matchesQuery(haystack: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  return q ? haystack.toLowerCase().includes(q) : false;
}

/** True when any extracted field matches the query (blank query never matches). */
export function rowMatches<T>(row: T, query: string, fields: (r: T) => string[]): boolean {
  for (const haystack of fields(row)) {
    if (matchesQuery(haystack, query)) return true;
  }
  return false;
}
