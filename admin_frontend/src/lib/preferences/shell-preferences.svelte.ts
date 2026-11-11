import { PREF_KEYS } from './keys';
import {
  readLocalBoolean,
  readLocalString,
  writeLocalBoolean,
  writeLocalString
} from './storage';

// UI kit step 1d: light/dark is no longer kept here; mode-watcher owns it (see routes/+layout.svelte
// and app.html).
export function createShellPreferences() {
  let sidebarCollapsed = $state(false);
  let selectedWorkspace = $state<string | null>(null);

  function initialize() {
    sidebarCollapsed = readLocalBoolean(PREF_KEYS.sidebarCollapsed, false);
    selectedWorkspace = readLocalString(PREF_KEYS.selectedWorkspace);
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
    get sidebarCollapsed() {
      return sidebarCollapsed;
    },
    get selectedWorkspace() {
      return selectedWorkspace;
    },
    initialize,
    setSidebarCollapsed,
    toggleSidebar,
    setSelectedWorkspace
  };
}
