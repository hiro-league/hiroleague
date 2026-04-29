import { browser } from '$app/environment';
import { PREF_KEYS, type ThemePreference } from './keys';
import {
  readLocalBoolean,
  readLocalString,
  writeLocalBoolean,
  writeLocalString
} from './storage';

function detectDefaultTheme(): ThemePreference {
  if (!browser) return 'dark';
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function createShellPreferences() {
  let theme = $state<ThemePreference>('dark');
  let sidebarCollapsed = $state(false);
  let selectedWorkspace = $state<string | null>(null);

  function initialize() {
    const savedTheme = readLocalString(PREF_KEYS.theme);
    theme = savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : detectDefaultTheme();
    document.documentElement.dataset.theme = theme;

    sidebarCollapsed = readLocalBoolean(PREF_KEYS.sidebarCollapsed, false);
    selectedWorkspace = readLocalString(PREF_KEYS.selectedWorkspace);
  }

  function setTheme(nextTheme: ThemePreference) {
    theme = nextTheme;
    document.documentElement.dataset.theme = nextTheme;
    writeLocalString(PREF_KEYS.theme, nextTheme);
  }

  function toggleTheme() {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  }

  function setSidebarCollapsed(nextCollapsed: boolean) {
    sidebarCollapsed = nextCollapsed;
    writeLocalBoolean(PREF_KEYS.sidebarCollapsed, nextCollapsed);
  }

  function toggleSidebar() {
    setSidebarCollapsed(!sidebarCollapsed);
  }

  function setSelectedWorkspace(workspaceId: string | null) {
    selectedWorkspace = workspaceId;
    if (workspaceId) {
      writeLocalString(PREF_KEYS.selectedWorkspace, workspaceId);
    }
  }

  return {
    get theme() {
      return theme;
    },
    get sidebarCollapsed() {
      return sidebarCollapsed;
    },
    get selectedWorkspace() {
      return selectedWorkspace;
    },
    initialize,
    setTheme,
    toggleTheme,
    setSidebarCollapsed,
    toggleSidebar,
    setSelectedWorkspace
  };
}
