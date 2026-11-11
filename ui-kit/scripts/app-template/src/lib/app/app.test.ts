import { describe, expect, it } from 'vitest';
import type { Me } from '$hiro-app/api';
import { menuFor } from '$kit/components/menu';
import { firstPage, pageAllowed } from '$kit/state/pages';

// The app's menu and pages agree (the kit tests the rules themselves; this guards this app's two lists).
const owner = { owner: true, state: 'ok', access: {} } as unknown as Me;

describe('menu and pages', () => {
	it('gives an owner every menu page, and each is a page that may be opened', () => {
		const pages = menuFor(owner).flatMap((g) => g.pages);
		expect(pages.length).toBeGreaterThan(0);
		for (const p of pages) expect(pageAllowed(owner, p.route)).toBe(true);
	});

	it('starts an owner on the first page', () => {
		expect(firstPage(owner)).toBe('/');
	});
});
