export type NavItem = {
  label: string;
  path: string;
  icon: string;
  group: 'Core' | 'AI Models' | 'Communication' | 'Operations';
};

export const navItems: NavItem[] = [
  { group: 'Core', label: 'Dashboard', path: '/', icon: 'grid' },
  { group: 'Core', label: 'Server', path: '/server/', icon: 'server' },
  { group: 'AI Models', label: 'Model Catalog', path: '/catalog/', icon: 'book' },
  { group: 'AI Models', label: 'Active Providers', path: '/active-providers/', icon: 'key' },
  { group: 'Communication', label: 'Channels & Devices', path: '/channels-devices/', icon: 'cpu' },
  { group: 'Communication', label: 'Characters', path: '/characters/', icon: 'user' },
  { group: 'Communication', label: 'Chat channels', path: '/chats/', icon: 'message' },
  { group: 'Operations', label: 'Logs', path: '/logs/', icon: 'list' },
  { group: 'Operations', label: 'Metrics', path: '/metrics/', icon: 'activity' }
];
