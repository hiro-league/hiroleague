// The admin's pages for the shared UI kit: the right that opens each, and whether this build has it. Made from
// the one list of pages (lib/shell/nav.ts), so a page is declared once. The rules that read this list (who may
// open a page, what is in their menu): $kit/state/pages.
import type { Page } from '$kit/state/pages';
import { isFeatureActive } from '$lib/shell/features';
import { navItems } from '$lib/shell/nav';

export const PAGES: Page[] = navItems.map((item) => ({
  route: item.path,
  // the kit asks for a feature at a level; the admin's one right (`open_settings`) is the feature "settings"
  any: ['settings'],
  need: 'use',
  // a feature the ledger turns off (lib/shell/features.ts) is in nobody's menu, and its page says so
  inBuild: item.feature ? () => isFeatureActive(item.feature!) : undefined
}));
