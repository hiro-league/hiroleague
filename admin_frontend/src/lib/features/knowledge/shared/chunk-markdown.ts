/**
 * Chunk bodies often retain markdown headings and end with `---`.
 * Without a blank line before a thematic-break line, parsers treat `---` as
 * setext underline and promote the preceding paragraph to a huge heading.
 */
export function prepareChunkMarkdownForPreview(raw: string | null | undefined): string {
  const text = (raw ?? '').trim();
  if (!text) return '';
  return text.replace(/\n(?=[ \t]*(?:-{3,}|={3,})[ \t]*(?:\n|$))/g, '\n\n');
}
