// mockup: the one list's two rules, the order of its rows and what its Status column says.
import { describe, expect, it } from 'vitest';
import { MOCK_EXTENSIONS, sortExtensions, statusOf, type MockExtension } from './one-list-mock';

const base = MOCK_EXTENSIONS.find((r) => r.name === 'whatsapp') as MockExtension;

describe('sortExtensions', () => {
  it('puts channels first, then apps, each by label', () => {
    const sorted = sortExtensions(MOCK_EXTENSIONS);
    const kinds = sorted.map((r) => r.kind);
    expect(kinds.indexOf('app')).toBe(kinds.lastIndexOf('channel') + 1);
    const apps = sorted.filter((r) => r.kind === 'app').map((r) => r.label);
    expect(apps).toEqual([...apps].sort((a, b) => a.localeCompare(b)));
  });
});

describe('statusOf', () => {
  it('says off before anything else', () => {
    expect(statusOf({ ...base, enabled: false, connected: false })).toEqual({ tone: 'off', text: 'Off' });
  });
  it('says not connected for an app that is away', () => {
    expect(statusOf({ ...base, enabled: null, connected: false, link: undefined }).text).toBe('Not connected');
  });
  it("names a channel whose account isn't linked", () => {
    expect(statusOf({ ...base, link: { linked: false, account: '' } })).toEqual({
      tone: 'warn',
      text: 'Connected, not linked'
    });
  });
  it('says connected when all is well', () => {
    expect(statusOf(base)).toEqual({ tone: 'ok', text: 'Connected' });
  });
});
