import DOMPurify from 'dompurify';

/** Sanitize a server-rendered QR SVG string before injecting it via {@html}. */
export function sanitizeQrSvg(raw: string): string {
  if (!raw) return '';
  return DOMPurify.sanitize(raw, { USE_PROFILES: { svg: true, svgFilters: true } });
}
