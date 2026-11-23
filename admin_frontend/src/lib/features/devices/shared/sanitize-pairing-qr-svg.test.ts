import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
  sanitize: vi.fn((raw: string) => raw)
}));

vi.mock('dompurify', () => ({
  default: { sanitize: h.sanitize }
}));

import { sanitizePairingQrSvg } from './sanitize-pairing-qr-svg';

beforeEach(() => {
  vi.clearAllMocks();
  h.sanitize.mockImplementation((raw: string) => raw);
});

describe('sanitizePairingQrSvg', () => {
  it('sanitizes with the SVG profile before html injection', () => {
    const svg = '<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>';
    expect(sanitizePairingQrSvg(svg)).toBe(svg);
    expect(h.sanitize).toHaveBeenCalledWith(svg, {
      USE_PROFILES: { svg: true, svgFilters: true }
    });
  });

  it('returns whatever DOMPurify produces', () => {
    h.sanitize.mockReturnValue('<svg></svg>');
    expect(sanitizePairingQrSvg('<svg><script>alert(1)</script></svg>')).toBe('<svg></svg>');
  });
});
