// The admin's pages for the shared UI kit: the core features that open each, and whether this build has it. Made
// from the one list of pages (lib/shell/nav.ts), so a page is declared once. The rules that read this list (who may
// open a page, what is in their menu): $kit/state/pages.
import type { Page } from '$kit/state/pages';
import { pageInBuild, navItems } from '$lib/shell/nav';

export const PAGES: Page[] = navItems.map((item) => ({
  route: item.path,
  // Permissions phase 2: any of the page's core features, at least to see it (a grant for their own things opens
  // nothing here: lib/shell/core-access.ts)
  any: [...item.features],
  need: 'see',
  ownerOnly: item.ownerOnly,
  // a feature the ledger turns off (lib/shell/features.ts) is in nobody's menu, and its page says so
  inBuild: item.ledger ? () => pageInBuild(item) : undefined
}));
