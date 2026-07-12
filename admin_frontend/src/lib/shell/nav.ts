import type { FeatureId } from './features';

export type NavItem = {
  label: string;
  path: string;
  icon: string;
  group: 'Core' | 'Configuration' | 'Communication' | 'Operations';
  /** When set, the item is only shown while that feature is active (see features.ts). */
  feature?: FeatureId;
};

export const navItems: NavItem[] = [
  { group: 'Core', label: 'Dashboard', path: '/', icon: 'grid' },
  { group: 'Core', label: 'Server', path: '/server/', icon: 'server' },
  { group: 'Communication', label: 'Channels & Devices', path: '/channels-devices/', icon: 'cpu' },
  { group: 'Communication', label: 'Characters', path: '/characters/', icon: 'user' },
  { group: 'Communication', label: 'Chat channels', path: '/chats/', icon: 'message' },
  { group: 'Operations', label: 'Knowledge', path: '/knowledge/', icon: 'database', feature: 'knowledge' },
  { group: 'Operations', label: 'Memories', path: '/memories/', icon: 'brain' },
  { group: 'Operations', label: 'Image Lab', path: '/image-lab/', icon: 'image', feature: 'image_lab' },
  { group: 'Operations', label: 'Eval', path: '/eval/', icon: 'flask', feature: 'eval' },
  // Configuration moved to the end of the sidebar; Logs moved to the end of this group.
  { group: 'Configuration', label: 'Providers/Models', path: '/catalog/', icon: 'book' },
  { group: 'Configuration', label: 'Settings', path: '/preferences/', icon: 'settings' },
  { group: 'Configuration', label: 'Logs', path: '/logs/', icon: 'list' }
];
