/**
 * "Show advanced" plumbing for the Settings page.
 *
 * Fields carry a display-only `advanced` flag in the preferences schema (see
 * `preferences_schema.py`). The page hides advanced fields behind a global toggle, and a card
 * whose every field is hidden collapses out of view. Two pieces of context wire that up:
 *
 *  - `AdvancedVisibility` — one global, session-persisted `showAdvanced` boolean, provided by the
 *    Settings page and read by every field gate (`usePrefFieldVisibility`).
 *  - `PrefFieldRegistry` — one per card (`PrefSectionCard`); each field registers a `getVisible`
 *    probe so the card knows whether any of its fields remain visible.
 *
 * The flag never round-trips to `preferences.json` — it's purely presentation.
 */
import { getContext, onMount, setContext } from 'svelte';
import { PREF_KEYS } from '$lib/preferences/keys';
import { readSessionString, writeSessionString } from '$lib/preferences/storage';

const ADVANCED_VISIBILITY = Symbol('pref-advanced-visibility');
const FIELD_REGISTRY = Symbol('pref-field-visibility-registry');

export type AdvancedVisibility = {
  /** When false, fields tagged `advanced` are hidden (default). */
  readonly showAdvanced: boolean;
  toggle: () => void;
  set: (next: boolean) => void;
};

/** Global, session-persisted "show advanced" toggle. Default off ⇒ basic-only view. */
export function createAdvancedVisibility(): AdvancedVisibility {
  let show = $state(readSessionString(PREF_KEYS.preferencesShowAdvanced) === 'true');

  function set(next: boolean) {
    show = next;
    writeSessionString(PREF_KEYS.preferencesShowAdvanced, String(next));
  }

  return {
    get showAdvanced() {
      return show;
    },
    toggle() {
      set(!show);
    },
    set
  };
}

export function provideAdvancedVisibility(visibility: AdvancedVisibility): void {
  setContext(ADVANCED_VISIBILITY, visibility);
}

function useAdvancedVisibility(): AdvancedVisibility | undefined {
  return getContext<AdvancedVisibility>(ADVANCED_VISIBILITY);
}

export type PrefFieldRegistry = {
  /** Register a visibility probe for one field; returns an unregister cleanup. */
  register: (getVisible: () => boolean) => () => void;
  /** True once at least one field has registered (so no-field cards never auto-hide). */
  readonly hasFields: boolean;
  /** True while any registered field is currently visible. */
  readonly anyVisible: boolean;
};

/** Per-card registry of field visibility probes, used by `PrefSectionCard` to auto-hide empties. */
export function createPrefFieldRegistry(): PrefFieldRegistry {
  const probes = new Set<() => boolean>();
  // Bumped on register/unregister so the derived recomputes membership; the toggle's own $state is
  // tracked separately by calling each probe inside the `$derived.by` below.
  let revision = $state(0);

  function register(getVisible: () => boolean) {
    probes.add(getVisible);
    revision += 1;
    return () => {
      probes.delete(getVisible);
      revision += 1;
    };
  }

  const hasFields = $derived.by(() => {
    revision;
    return probes.size > 0;
  });

  const anyVisible = $derived.by(() => {
    revision;
    // Calling each probe here tracks `showAdvanced` (a $state read inside the probe), so flipping
    // the toggle recomputes this without a manual revision bump.
    for (const getVisible of probes) {
      if (getVisible()) return true;
    }
    return false;
  });

  return {
    register,
    get hasFields() {
      return hasFields;
    },
    get anyVisible() {
      return anyVisible;
    }
  };
}

export function providePrefFieldRegistry(registry: PrefFieldRegistry): void {
  setContext(FIELD_REGISTRY, registry);
}

export function usePrefFieldRegistry(): PrefFieldRegistry | undefined {
  return getContext<PrefFieldRegistry>(FIELD_REGISTRY);
}

/**
 * Field-level visibility gate. Computes whether a field should render (basic fields always; advanced
 * fields only when the toggle is on) and registers a probe with the enclosing card so it can
 * auto-hide when empty. Outside the Settings contexts it degrades to always-visible.
 *
 * Call once at the top of a `Pref*Field` widget and render its control under `{#if vis.visible}`.
 */
export function usePrefFieldVisibility(isAdvanced: () => boolean): { readonly visible: boolean } {
  const visibility = useAdvancedVisibility();
  const registry = usePrefFieldRegistry();

  const visible = $derived(!isAdvanced() || (visibility?.showAdvanced ?? true));

  onMount(() => registry?.register(() => visible));

  return {
    get visible() {
      return visible;
    }
  };
}

/**
 * Advanced gate WITHOUT registering a card auto-hide probe. Use for an advanced field rendered as a
 * raw control (not a `Pref*Field`) inside a card whose OTHER content doesn't register — registering
 * here would make that field the card's only probe and wrongly collapse the whole card when advanced
 * is off. Same visibility rule as `usePrefFieldVisibility`, just no registration.
 */
export function usePrefAdvancedVisibility(isAdvanced: () => boolean): { readonly visible: boolean } {
  const visibility = useAdvancedVisibility();
  const visible = $derived(!isAdvanced() || (visibility?.showAdvanced ?? true));
  return {
    get visible() {
      return visible;
    }
  };
}
