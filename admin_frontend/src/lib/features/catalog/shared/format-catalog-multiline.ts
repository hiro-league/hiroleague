/**
 * Turn YAML folded `details: |` blocks into display paragraphs.
 * Single newlines are editorial line wraps; blank lines start a new paragraph.
 */
export function catalogMultilineParagraphs(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  return trimmed
    .split(/\n{2,}/)
    .map((block) => block.replace(/\s*\n\s*/g, ' ').replace(/\s+/g, ' ').trim())
    .filter(Boolean);
}
