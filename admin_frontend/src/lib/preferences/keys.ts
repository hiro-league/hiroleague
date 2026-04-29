export const PREF_KEYS = {
  theme: 'hiro.admin.theme',
  sidebarCollapsed: 'hiro.admin.sidebar.collapsed',
  selectedWorkspace: 'hiro.admin.selectedWorkspace',
  serverActiveTab: 'hiro.admin.server.activeTab',
  catalogActiveTab: 'hiro.admin.catalog.activeTab'
} as const;

export type ThemePreference = 'light' | 'dark';
export type ServerTabPreference = 'workspaces' | 'gateways';
export type CatalogTabPreference = 'providers' | 'models' | 'active-providers';
