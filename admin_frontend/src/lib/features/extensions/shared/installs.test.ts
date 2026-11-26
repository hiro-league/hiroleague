import { describe, expect, it } from 'vitest';
import type { ExtensionRow, InstallRow, PackageOffer } from '$lib/api/extensions';
import { compareVersions, installAsRow, installLine, setupHref, unpairedInstalls, upgradeOffer } from './installs';

const hello: InstallRow = {
  key: 'example.hello', title: 'Hello', version: '0.1.0', port: 8190, state: 'running', step: '',
  service: 'hiro-example-hello', running: true, folder: '/opt/hiroleague/apps/example.hello',
  data: '/opt/hiroleague/apps/example.hello/data', installed_at: '', approved: []
};
const offer = (version: string, key = 'example.hello'): PackageOffer =>
  ({ file: `${key}-${version}.zip`, key, title: 'Hello', version, offer: 'upgrade', command: '' });

describe('installed apps', () => {
  it('says the service and the install state', () => {
    expect(installLine(hello)).toEqual({ tone: 'ok', text: 'Running' });
    expect(installLine({ ...hello, running: false })).toEqual({ tone: 'off', text: 'Stopped' });
    expect(installLine({ ...hello, running: null }).tone).toBe('warn');
    expect(installLine({ ...hello, state: 'upgrading', step: 'trying its migrations on a copy' }).text)
      .toBe('Upgrading: trying its migrations on a copy');
    expect(installLine({ ...hello, state: 'failed', step: 'remove it' }).tone).toBe('error');
  });

  it('offers the newest newer package of the same app, and only to a running install', () => {
    expect(compareVersions('0.1.10', '0.1.9')).toBe(1);
    const packages = [offer('0.1.1'), offer('0.1.2'), offer('0.0.9'), offer('0.3.0', 'acme.notes')];
    expect(upgradeOffer(packages, hello)?.version).toBe('0.1.2');
    expect(upgradeOffer(packages, { ...hello, state: 'failed' })).toBeNull();
    expect(upgradeOffer([offer('0.1.0')], hello)).toBeNull();
  });

  it("links a setup item to the app's own page", () => {
    const row = { ...installAsRow(hello), site: 'http://example-hello.hiro.local/' } as ExtensionRow;
    expect(setupHref(row, { title: 'Write its greeting', app: 'example.hello', path: '/settings' }))
      .toBe('http://example-hello.hiro.local/settings');
    expect(setupHref(row, { title: 'x', app: null, path: '/people' })).toBe('/people');
    expect(setupHref({ ...row, site: '' }, { title: 'x', app: 'example.hello', path: '/' })).toBe('');
  });

  it('lists an install with no extension row of its own as a row', () => {
    const paired = installAsRow({ ...hello, key: 'acme.notes' });
    const rows = unpairedInstalls([hello, { ...hello, key: 'acme.notes' }], [paired]);
    expect(rows.map((r) => [r.extension_id, r.label])).toEqual([['install:example.hello', 'Hello']]);
  });
});
