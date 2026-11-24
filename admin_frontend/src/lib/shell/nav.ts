import { isFeatureActive, type FeatureId } from './features';
import { ADMIN_FEATURES, type CoreFeature } from './core-access';

export type NavItem = {
  label: string;
  path: string;
  icon: string;
  group: 'Core' | 'Configuration' | 'Communication' | 'Operations';
  /** When set, the item is only shown while that ledger feature is active (see features.ts). */
  ledger?: FeatureId;
  /** Permissions phase 2: the core features that open the page, any of them (core-access.ts). */
  features: readonly CoreFeature[];
  /** The owner's alone, whatever the person's permissions: People and roles. */
  ownerOnly?: boolean;
};

/** Whether this build has the page: a page whose ledger feature is off is in nobody's menu. */
export const pageInBuild = (item: NavItem): boolean => !item.ledger || isFeatureActive(item.ledger);

export const navItems: NavItem[] = [
  // The Dashboard is anyone's who opens the admin; each card shows under its page's feature.
  { group: 'Core', label: 'Dashboard', path: '/', icon: 'grid', features: ADMIN_FEATURES },
  { group: 'Core', label: 'Server', path: '/server', icon: 'server', features: ['server'] },
  { group: 'Core', label: 'Extensions', path: '/extensions', icon: 'puzzle', features: ['extensions'] },
  // Phase 6: the family list, its roles and admin sign-ins; people and roles are the owner's.
  { group: 'Core', label: 'People', path: '/people', icon: 'users', features: [], ownerOnly: true },
  // The family's devices; the channels they chat through are on Extensions (Unified communication, phase 2).
  { group: 'Communication', label: 'Devices', path: '/devices', icon: 'cpu', ledger: 'devices', features: ['devices'] },
  { group: 'Communication', label: 'Characters', path: '/characters', icon: 'user', features: ['assistant.characters'] },
  { group: 'Communication', label: 'Chat channels', path: '/chats', icon: 'message', features: ['conversations'] },
  { group: 'Operations', label: 'Knowledge', path: '/knowledge', icon: 'database', ledger: 'knowledge', features: ['knowledge'] },
  { group: 'Operations', label: 'Memories', path: '/memories', icon: 'brain', features: ['memories'] },
  { group: 'Operations', label: 'Image Lab', path: '/image-lab', icon: 'image', ledger: 'image_lab', features: ['ai.images'] },
  { group: 'Configuration', label: 'Providers/Models', path: '/catalog', icon: 'book', features: ['ai.providers', 'ai.profiles'] },
  { group: 'Configuration', label: 'Settings', path: '/preferences', icon: 'settings', features: ['settings'] },
  { group: 'Configuration', label: 'Logs', path: '/logs', icon: 'list', features: ['logs', 'logs.runs', 'logs.usage'] },
  { group: 'Configuration', label: 'UI kit', path: '/ui-kit', icon: 'palette', ledger: 'ui_kit', features: ['settings'] }
];
