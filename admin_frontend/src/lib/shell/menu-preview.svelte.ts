// mockup: Permissions phase 2. The admin as a role would see it: its menu and its pages' tabs from that role's keys
// in the core (People → Roles, "View as"). Gone when the menu reads the signed-in person's own keys.
import { who } from '$kit/state/who.svelte';

type Preview = { roleName: string; keys: string[] };

function createMenuPreview() {
  let current = $state<Preview | null>(null);
  return {
    get current() {
      return current;
    },
    start(roleName: string, keys: string[]) {
      current = { roleName, keys: [...keys] };
      void who.load();
    },
    stop() {
      current = null;
      void who.load();
    }
  };
}

export const menuPreview = createMenuPreview();
