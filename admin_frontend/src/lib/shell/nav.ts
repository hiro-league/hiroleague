import { isFeatureActive, type FeatureId } from './features';

/**
 * A right a person's role can have, as `/auth/me` reports it. Today there is one: opening
 * HiroLeague's settings (`can_open_settings`).
 */
export type PageRight = 'open_settings';

export type NavItem = {
  label: string;
  path: string;
  icon: string;
  group: 'Core' | 'Configuration' | 'Communication' | 'Operations';
  /** When set, the item is only shown while that feature is active (see features.ts). */
  feature?: FeatureId;
  /** The right that opens the page (UI kit step 1d: declared per page, beside its build flag). */
  right: PageRight;
};

/** A page shows when its feature is in the build and the person's role has the page's right. */
export function pageShows(item: NavItem, has: (right: PageRight) => boolean): boolean {
  return (!item.feature || isFeatureActive(item.feature)) && has(item.right);
}

// Every page declares the one right there is today; the list is ready for per-page rights.
export const navItems: NavItem[] = [
  { group: 'Core', label: 'Dashboard', path: '/', icon: 'grid', right: 'open_settings' },
  { group: 'Core', label: 'Server', path: '/server/', icon: 'server', right: 'open_settings' },
  { group: 'Core', label: 'Extensions', path: '/extensions/', icon: 'puzzle', right: 'open_settings' },
  // Phase 6: the family list, its roles and admin sign-ins.
  { group: 'Core', label: 'People', path: '/people/', icon: 'users', right: 'open_settings' },
  { group: 'Communication', label: 'Channels & Devices', path: '/channels-devices/', icon: 'cpu', right: 'open_settings' },
  { group: 'Communication', label: 'Characters', path: '/characters/', icon: 'user', right: 'open_settings' },
  { group: 'Communication', label: 'Chat channels', path: '/chats/', icon: 'message', right: 'open_settings' },
  { group: 'Operations', label: 'Knowledge', path: '/knowledge/', icon: 'database', feature: 'knowledge', right: 'open_settings' },
  { group: 'Operations', label: 'Memories', path: '/memories/', icon: 'brain', right: 'open_settings' },
  { group: 'Operations', label: 'Image Lab', path: '/image-lab/', icon: 'image', feature: 'image_lab', right: 'open_settings' },
  { group: 'Operations', label: 'Eval', path: '/eval/', icon: 'flask', feature: 'eval', right: 'open_settings' },
  // Configuration moved to the end of the sidebar; Logs moved to the end of this group.
  { group: 'Configuration', label: 'Providers/Models', path: '/catalog/', icon: 'book', right: 'open_settings' },
  { group: 'Configuration', label: 'Settings', path: '/preferences/', icon: 'settings', right: 'open_settings' },
  { group: 'Configuration', label: 'Logs', path: '/logs/', icon: 'list', right: 'open_settings' }
];
