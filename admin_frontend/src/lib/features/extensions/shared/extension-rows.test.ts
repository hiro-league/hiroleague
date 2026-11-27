import { describe, expect, it } from 'vitest';
import type { ExtensionRow } from '$lib/api/extensions';
import { countKinds, hasSettings, ofKinds, sortExtensions, statusOf, statusTime } from './extension-rows';

function row(over: Partial<ExtensionRow>): ExtensionRow {
  return {
    extension_id: over.name ?? 'x',
    name: 'x',
    label: 'X',
    kind: 'app',
    version: '0.1.0',
    description: '',
    paired_at: null,
    last_seen: null,
    relays_chat: false,
    started_by_core: false,
    enabled: null,
    mandatory: false,
    has_settings: false,
    pairing: '',
    site: '',
    offers: [],
    uses: [],
    connected: true,
    connected_at: '2026-11-23T10:00:00Z',
    remote: null,
    linked: null,
    account: '',
    pending: false,
    waits: false,
    waiting_count: 0,
    ...over
  };
}

const whatsapp = row({ name: 'whatsapp', label: 'WhatsApp', kind: 'channel', started_by_core: true, enabled: true, has_settings: true, pairing: 'qr', linked: true });
const devices = row({ name: 'devices', label: 'Devices', kind: 'channel', started_by_core: true, enabled: true });
const home = row({ name: 'home', label: 'Home' });
const codehiro = row({ name: 'code', label: 'CodeHiro' });

describe('sortExtensions', () => {
  it('puts channels first, then apps, each by label', () => {
    expect(sortExtensions([home, whatsapp, codehiro, devices]).map((r) => r.name)).toEqual([
      'devices',
      'whatsapp',
      'code',
      'home'
    ]);
  });
});

describe('ofKinds and countKinds', () => {
  const rows = [whatsapp, devices, home];
  it('keeps every row when no kind is picked', () => {
    expect(ofKinds(rows, [])).toHaveLength(3);
  });
  it('keeps the kinds picked', () => {
    expect(ofKinds(rows, ['app']).map((r) => r.name)).toEqual(['home']);
    expect(ofKinds(rows, ['channel', 'app'])).toHaveLength(3);
  });
  it('counts each kind', () => {
    expect(countKinds(rows)).toEqual({ channel: 2, app: 1 });
  });
});

describe('statusOf', () => {
  it('says off before anything else', () => {
    expect(statusOf({ ...whatsapp, enabled: false, connected: false })).toEqual({ tone: 'off', text: 'Off' });
  });
  it('says not connected for an extension that is away', () => {
    expect(statusOf({ ...home, connected: false }).text).toBe('Not connected');
  });
  it("names a channel whose account isn't linked", () => {
    expect(statusOf({ ...whatsapp, linked: false })).toEqual({ tone: 'warn', text: 'Connected, not linked' });
  });
  it('says connected when all is well, an app included', () => {
    expect(statusOf(whatsapp).tone).toBe('ok');
    expect(statusOf(home)).toEqual({ tone: 'ok', text: 'Connected' });
  });
});

describe('statusTime', () => {
  it('gives when it connected, or when it was last seen, or nothing', () => {
    expect(statusTime(home)?.words).toBe('since');
    expect(statusTime({ ...home, connected: false, last_seen: '2026-11-22T10:00:00Z' })).toEqual({
      words: 'last seen',
      at: '2026-11-22T10:00:00Z'
    });
    expect(statusTime({ ...home, connected: false })).toBeNull();
  });
});

describe('hasSettings', () => {
  it('is true for a channel with a form or an account to link', () => {
    expect(hasSettings(whatsapp)).toBe(true);
    expect(hasSettings({ ...whatsapp, has_settings: false })).toBe(true);
  });
  it('is false for a channel with neither, and for an app', () => {
    expect(hasSettings(devices)).toBe(false);
    expect(hasSettings({ ...home, has_settings: true })).toBe(false);
  });
});
