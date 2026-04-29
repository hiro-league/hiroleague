export type NavItem = {
  label: string;
  path: string;
  icon: string;
  group: 'Core' | 'AI Models' | 'Operations' | 'Configuration';
};

export const navItems: NavItem[] = [
  { group: 'Core', label: 'Dashboard', path: '/', icon: 'grid' },
  { group: 'Core', label: 'Server', path: '/server/', icon: 'server' },
  { group: 'AI Models', label: 'Catalog', path: '/catalog/', icon: 'book' },
  { group: 'Operations', label: 'Logs', path: '#logs', icon: 'list' },
  { group: 'Operations', label: 'Metrics', path: '#metrics', icon: 'activity' },
  { group: 'Operations', label: 'Devices', path: '#devices', icon: 'cpu' },
  { group: 'Configuration', label: 'Characters', path: '#characters', icon: 'user' },
  { group: 'Configuration', label: 'Providers', path: '#providers', icon: 'key' }
];
