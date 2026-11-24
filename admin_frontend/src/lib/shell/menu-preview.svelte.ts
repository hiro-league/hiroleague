// Permissions phase 2: the admin as a role's people see it (People → Roles, "View as"): its menu and its pages'
// tabs from the levels the core works out for that role, until Stop. Only the owner opens Roles, so only the owner
// views as a role; the calls the pages make are still the owner's.
import { who } from '$kit/state/who.svelte';

type Preview = { roleName: string; levels: Record<string, 'no' | 'see' | 'use'> };

function createMenuPreview() {
  let current = $state<Preview | null>(null);
  return {
    get current() {
      return current;
    },
    start(roleName: string, levels: Record<string, 'no' | 'see' | 'use'>) {
      current = { roleName, levels: { ...levels } };
      void who.load();
    },
    stop() {
      current = null;
      void who.load();
    }
  };
}

export const menuPreview = createMenuPreview();
