import DOMPurify from 'dompurify';

/**
 * Sanitize server-generated pairing QR SVG before `{@html}`.
 * Trust boundary: HiroServer `/devices/pairing-code` response only.
 */
export function sanitizePairingQrSvg(raw: string): string {
  return DOMPurify.sanitize(raw, { USE_PROFILES: { svg: true, svgFilters: true } });
}
