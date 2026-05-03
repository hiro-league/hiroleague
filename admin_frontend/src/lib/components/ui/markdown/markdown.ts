import DOMPurify from 'dompurify';
import { marked } from 'marked';

/** GitHub-flavored Markdown; sync compile for reactive previews in Svelte. */
marked.setOptions({
  gfm: true,
  breaks: false
});

/**
 * Markdown → sanitized HTML for `{@html}` rendering.
 * Admin routes use `ssr = false`; DOMPurify runs only in the browser bundle.
 */
export function renderSafeMarkdown(raw: string | null | undefined): string {
  const text = (raw ?? '').trim();
  if (!text) return '';
  const html = marked(text, { async: false }) as string;
  return DOMPurify.sanitize(html);
}
