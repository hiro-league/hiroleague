/**
 * "Panel" plumbing for the Settings page.
 *
 * A panel is a labeled group of related preference fields inside a section card with ONE group-level
 * reset (resets every member field to its default at once, instead of one dot per field). It mirrors
 * the `PrefFieldRegistry` advanced-visibility pattern: the panel provides a registry, and each
 * enclosed `Pref*Field` registers its dotted path so the panel can (a) tell whether any member
 * differs from its default and (b) reset them all. Membership also signals a field to hide its OWN
 * per-field reset dot (the panel owns the reset).
 *
 * Defaults are read from the generated effective-defaults tree, not per-leaf schema `default`, so
 * factory-seeded fields (e.g. `media.input.voice = true`) reset correctly — see `PrefPanel`.
 */
import { getContext, onMount, setContext } from 'svelte';

const PANEL_REGISTRY = Symbol('pref-panel-registry');

export type PrefPanelRegistry = {
  /** Register one member field's dotted path; returns an unregister cleanup. */
  register: (path: string) => () => void;
  /** Current member paths (revision-tracked so a panel's derived recomputes on (un)register). */
  readonly paths: string[];
};

/** Per-panel registry of member field paths, provided by `PrefPanel`. */
export function createPrefPanelRegistry(): PrefPanelRegistry {
  const members = new Set<string>();
  // Bumped on register/unregister so the `paths` derived (and any panel-side dirty check that reads
  // it) recomputes membership.
  let revision = $state(0);

  function register(path: string) {
    members.add(path);
    revision += 1;
    return () => {
      members.delete(path);
      revision += 1;
    };
  }

  const paths = $derived.by(() => {
    revision;
    return [...members];
  });

  return {
    register,
    get paths() {
      return paths;
    }
  };
}

export function providePrefPanelRegistry(registry: PrefPanelRegistry): void {
  setContext(PANEL_REGISTRY, registry);
}

function usePrefPanelRegistry(): PrefPanelRegistry | undefined {
  return getContext<PrefPanelRegistry>(PANEL_REGISTRY);
}

/**
 * Field-level panel membership. When a `Pref*Field` is rendered inside a `PrefPanel`, this registers
 * its path with the panel and reports `inPanel = true` so the field suppresses its own reset dot
 * (the panel's group reset replaces it). Outside a panel it degrades to a no-op (`inPanel = false`).
 *
 * Call once at the top of a `Pref*Field` widget. `inPanel` is fixed at init (context presence), so
 * no reactivity is needed for it.
 */
export function usePrefPanelMembership(getPath: () => string): { readonly inPanel: boolean } {
  const registry = usePrefPanelRegistry();
  // `getPath` is read at mount (a field's path is fixed for its lifetime); the getter form just
  // avoids capturing a prop's initial value eagerly (Svelte `state_referenced_locally`).
  onMount(() => registry?.register(getPath()));
  const inPanel = registry != null;
  return {
    get inPanel() {
      return inPanel;
    }
  };
}
