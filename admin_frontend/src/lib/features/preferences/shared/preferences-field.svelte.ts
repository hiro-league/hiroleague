/**
 * Shared per-field rune for the `Pref*Field` widgets.
 *
 * Tier-1 preferences refactor: every `Pref*Field` used to repeat the same ~15 lines (resolve schema
 * meta → label/hint, advanced-visibility gate, panel membership, and a "reset to default" affordance)
 * AND take the field value as a `bind:value`/`bind:checked` prop — so each call site named its dotted
 * `path` twice (once as the string, once as the binding expression), which could silently diverge.
 *
 * `usePrefField` centralizes both: it derives label/hint/visibility/reset from the schema, and it owns
 * the value via the dotted `path` (read with `getPreferenceByPath`, write with `setPreferenceByPath`
 * + `markDirty`). Widgets now `bind:` to `field.value`, so `path` is the single source of truth and
 * the call site collapses to `<PrefNumberField {ctrl} path="…" />`.
 */
import type { PreferenceFieldMeta } from '$lib/api/preferences-schema';
import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
import {
  getPreferenceByPath,
  setPreferenceByPath
} from '$lib/features/preferences/state/preferences-edits';
import { usePrefFieldVisibility } from './preferences-advanced.svelte';
import { usePrefPanelMembership } from './preferences-panel.svelte';
import {
  preferenceFieldMeta,
  preferenceHint,
  preferenceIsAdvanced,
  preferenceTitle,
  type PreferencePath
} from './preferences-schema';

export type PrefFieldState<T> = {
  /** Live schema metadata for the field (null when the running server's schema lacks the path). */
  readonly meta: PreferenceFieldMeta | null;
  /** Resolved display label (override → backend `title` → the raw path). */
  readonly label: string;
  /** Resolved hint (override → backend `description`). */
  readonly hint: string | undefined;
  /** Whether the field renders (basic always; advanced only when "show advanced" is on). */
  readonly visible: boolean;
  /** True when inside a `PrefPanel` (the panel owns the group reset, so hide the per-field dot). */
  readonly inPanel: boolean;
  /** Live value at `path` in the draft; assigning writes it back through the schema + marks dirty. */
  value: T;
  /** Schema default for the field (undefined when the field carries none). */
  readonly defaultValue: unknown;
  /** True when a per-field reset dot should show (has a default, differs from it, not in a panel). */
  readonly canReset: boolean;
  /** Restore the schema default through the same write path as a user edit. */
  reset: () => void;
};

type PrefFieldOptions = {
  /** Optional label override; omit to use the field's backend `title`. */
  label?: () => string | undefined;
  /** Optional hint override; omit to use the field's backend `description`. */
  hint?: () => string | undefined;
};

/**
 * Call once at the top of a `Pref*Field` widget's `<script>`. Returns a live view of the field bound
 * to its dotted `path`. `getCtrl`/`getPath` are getters (both are props) so reads stay reactive and we
 * avoid Svelte's `state_referenced_locally` warning.
 */
export function usePrefField<T = unknown>(
  getCtrl: () => PreferencesController,
  getPath: () => PreferencePath,
  opts: PrefFieldOptions = {}
): PrefFieldState<T> {
  const meta = $derived(preferenceFieldMeta(getCtrl().fieldSchema, getPath()));
  const label = $derived(opts.label?.() ?? preferenceTitle(meta) ?? getPath());
  const hint = $derived(opts.hint?.() ?? preferenceHint(meta));
  const vis = usePrefFieldVisibility(() => preferenceIsAdvanced(meta));
  const panel = usePrefPanelMembership(getPath);

  const current = $derived(getPreferenceByPath(getCtrl().draft, getPath()));
  const defaultValue = $derived(meta?.default);
  // null/undefined collapse to '' so a nullable-string field whose box is merely empty matches a null
  // default (no spurious reset dot). Numbers/booleans never reach the null branch.
  const norm = (v: unknown) => (v == null ? '' : v);
  const canReset = $derived(
    !panel.inPanel && defaultValue !== undefined && norm(current) !== norm(defaultValue)
  );

  function write(value: unknown) {
    const ctrl = getCtrl();
    if (!ctrl.draft) return;
    setPreferenceByPath(ctrl.draft, getPath(), value);
    ctrl.markDirty();
  }

  return {
    get meta() {
      return meta;
    },
    get label() {
      return label;
    },
    get hint() {
      return hint;
    },
    get visible() {
      return vis.visible;
    },
    get inPanel() {
      return panel.inPanel;
    },
    get value() {
      return current as T;
    },
    set value(v: T) {
      write(v);
    },
    get defaultValue() {
      return defaultValue;
    },
    get canReset() {
      return canReset;
    },
    reset() {
      if (defaultValue === undefined) return;
      write(defaultValue);
    }
  };
}
