import { describe, expect, it } from 'vitest';
import { adminUrl, formatStderrTime, gatewayHttpUrl, statusUrl, stderrTitle } from './server-format';

describe('formatStderrTime', () => {
  it('returns empty string for null or invalid input', () => {
    expect(formatStderrTime(null)).toBe('');
    expect(formatStderrTime('not-a-date')).toBe('');
  });

  it('formats a valid ISO timestamp', () => {
    const out = formatStderrTime('2026-06-19T14:05:00Z');
    expect(out).not.toBe('');
    // Locale-dependent exact string; assert it carries the date pieces.
    expect(out).toMatch(/Jun/);
  });
});

describe('stderrTitle', () => {
  it('omits the "updated" clause when mtime is missing', () => {
    expect(stderrTitle(null, 512)).toBe('stderr.log (512 B)');
  });

  it('includes the updated clause and size when mtime is present', () => {
    expect(stderrTitle('2026-06-19T14:05:00Z', 2048)).toMatch(/^stderr\.log updated .+ \(2\.0 KB\)$/);
  });
});

describe('gatewayHttpUrl', () => {
  it('returns null for null input', () => {
    expect(gatewayHttpUrl(null)).toBeNull();
  });

  it('maps ws/wss to http/https', () => {
    expect(gatewayHttpUrl('ws://host:8765')).toBe('http://host:8765');
    expect(gatewayHttpUrl('wss://host:8765')).toBe('https://host:8765');
  });
});

describe('statusUrl / adminUrl', () => {
  it('builds local loopback URLs from ports', () => {
    expect(statusUrl(18080)).toBe('http://127.0.0.1:18080/status');
    expect(adminUrl(18083)).toBe('http://127.0.0.1:18083/');
  });
});
