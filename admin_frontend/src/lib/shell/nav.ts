export type NavItem = {
  label: string;
  path: string;
  icon: string;
  group: 'Core' | 'Configuration' | 'Communication' | 'Operations';
};

export const navItems: NavItem[] = [
  { group: 'Core', label: 'Dashboard', path: '/', icon: 'grid' },
  { group: 'Core', label: 'Server', path: '/server/', icon: 'server' },
  { group: 'Configuration', label: 'Providers/Models', path: '/catalog/', icon: 'book' },
  { group: 'Configuration', label: 'Preferences', path: '/preferences/', icon: 'settings' },
  { group: 'Communication', label: 'Channels & Devices', path: '/channels-devices/', icon: 'cpu' },
  { group: 'Communication', label: 'Characters', path: '/characters/', icon: 'user' },
  { group: 'Communication', label: 'Chat channels', path: '/chats/', icon: 'message' },
  { group: 'Operations', label: 'Knowledge', path: '/knowledge/', icon: 'database' },
  { group: 'Operations', label: 'Logs', path: '/logs/', icon: 'list' },
  { group: 'Operations', label: 'Memories', path: '/memories/', icon: 'brain' }
];
