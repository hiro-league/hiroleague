// The rules over an app's pages, with pages of the test's own (an app's real list is tested beside it, in lib/app).
import { describe, expect, it, vi } from 'vitest';
import type { Me } from '$hiro-app/api';

let ready = false;
vi.mock('$hiro-app/pages', () => ({
	PAGES: [
		{ route: '/', any: ['home'] },
		{ route: '/server/', any: ['settings'], need: 'use' }, // an app whose routes end in a slash
		{ route: '/lab', any: ['lab'], inBuild: () => ready }
	]
}));

const { firstPage, inMenu, pageAllowed, trimSlash, under } = await import('./pages');

const me = (access: Record<string, string>, owner = false) => ({ owner, state: 'ok', access }) as unknown as Me;

describe('page rules', () => {
	it('reads an address with or without its last slash', () => {
		expect(trimSlash('/server/')).toBe('/server');
		expect(trimSlash('/server')).toBe('/server');
		expect(trimSlash('/')).toBe('/');
		expect(under('/server/', '/server')).toBe(true);
		expect(under('/server', '/server/')).toBe(true);
		expect(under('/server/', '/server/logs')).toBe(true);
		expect(under('/server', '/servers')).toBe(false);
		expect(under('/', '/server')).toBe(false);
		expect(under('/', null)).toBe(false);
	});

	it('opens a page whose route ends in a slash from either address', () => {
		const admin = me({ settings: 'use' });
		expect(pageAllowed(admin, '/server')).toBe(true);
		expect(pageAllowed(admin, '/server/')).toBe(true);
		expect(pageAllowed(me({ settings: 'see' }), '/server/')).toBe(false);
		expect(inMenu(admin, '/server')).toBe(true);
	});

	it('gives nobody a page this build leaves out, an owner neither', () => {
		const owner = me({}, true);
		ready = false;
		expect(pageAllowed(owner, '/lab')).toBe(false);
		expect(pageAllowed(me({ lab: 'use' }), '/lab')).toBe(false);
		expect(inMenu(owner, '/lab')).toBe(false);
		expect(firstPage(me({ lab: 'use' }))).toBe(null);
		ready = true;
		expect(pageAllowed(owner, '/lab')).toBe(true);
		expect(pageAllowed(me({ lab: 'see' }), '/lab')).toBe(true);
		expect(firstPage(me({ lab: 'use' }))).toBe('/lab');
	});
});
