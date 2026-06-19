/**
 * Case-insensitive text highlighting for the eval corpus/episode search.
 *
 * Splits `text` into `{text, hit}` segments around matches of `term`, so the caller can wrap
 * matches in <mark> WITHOUT {@html} — no injection risk from corpus content. Shared by the
 * Corpus review section and the corpus tab inside the retrieval/ingest trace dialogs.
 */
export type HighlightSegment = { text: string; hit: boolean };

export function highlightSegments(text: string, term: string): HighlightSegment[] {
  const needle = term.trim().toLowerCase();
  if (!needle) return [{ text, hit: false }];
  const out: HighlightSegment[] = [];
  const lower = text.toLowerCase();
  let i = 0;
  while (i < text.length) {
    const idx = lower.indexOf(needle, i);
    if (idx === -1) {
      out.push({ text: text.slice(i), hit: false });
      break;
    }
    if (idx > i) out.push({ text: text.slice(i, idx), hit: false });
    out.push({ text: text.slice(idx, idx + needle.length), hit: true });
    i = idx + needle.length;
  }
  return out;
}
