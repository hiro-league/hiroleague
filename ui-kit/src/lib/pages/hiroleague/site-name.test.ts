import { describe, expect, it } from 'vitest';
import { APP } from '$hiro-app/app';
import type { SiteNameOut } from './api';
import { addressFor, claimSaid } from './site-name';

describe('addressFor', () => {
	it('makes a subdomain of hiro.local or a one-word .local name', () => {
		expect(addressFor('net', 'subdomain')).toBe('http://net.hiro.local');
		expect(addressFor(' Abc ', 'local')).toBe('http://abc.local');
		expect(addressFor('net.hiro.local', 'subdomain')).toBe('http://net.hiro.local'); // the whole name pasted
		expect(addressFor('  ', 'local')).toBe('');
	});
});

describe('claimSaid', () => {
	const answer = (over: Partial<SiteNameOut>): SiteNameOut => ({
		name: 'net.hiro.local',
		url: 'http://net.hiro.local',
		published: true,
		proxied: true,
		note: '',
		status: { url: '', status: 'connected' },
		...over
	});

	it('is fine when the name is published and proxied', () => {
		expect(claimSaid(answer({}))).toEqual({
			text: `${APP.name} is now at http://net.hiro.local: HiroLeague published the name and points it here.`,
			ok: true
		});
	});

	it("says what isn't set up yet, with the core's note", () => {
		const r = claimSaid(answer({ published: false, proxied: false, note: 'This server isn’t set up to publish names.' }));
		expect(r.ok).toBe(false);
		expect(r.text).toBe(
			`${APP.name} is now at http://net.hiro.local, but the name is not published on the network and not proxied to ` +
				`${APP.name} yet. This server isn’t set up to publish names.`
		);
		expect(claimSaid(answer({ proxied: false })).text).toContain(`is not proxied to ${APP.name} yet.`);
	});
});
