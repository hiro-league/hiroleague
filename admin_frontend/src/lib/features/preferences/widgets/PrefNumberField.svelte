<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { usePrefFieldVisibility } from '$lib/features/preferences/shared/preferences-advanced.svelte';
  import { usePrefPanelMembership } from '$lib/features/preferences/shared/preferences-panel.svelte';
  import {
    preferenceFieldMeta,
    preferenceHint,
    preferenceIsAdvanced,
    preferenceNumberBounds,
    preferenceTitle,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
    value?: number;
    class?: string;
    inputClass?: string;
    disabled?: boolean;
    /** Optional override of the schema description (rare card-local copy). */
    hint?: string;
  };

  let {
    ctrl,
    path,
    label,
    value = $bindable(),
    class: className = '',
    inputClass = ADMIN_SELECT_LG,
    disabled = false,
    hint: hintOverride
  }: Props = $props();

  const meta = $derived(preferenceFieldMeta(ctrl.fieldSchema, path));
  const resolvedLabel = $derived(label ?? preferenceTitle(meta) ?? path);
  const bounds = $derived(preferenceNumberBounds(meta));
  const hint = $derived(hintOverride ?? preferenceHint(meta));
  const vis = usePrefFieldVisibility(() => preferenceIsAdvanced(meta));

  // "Reset to default" affordance: only when the schema carries a numeric default and the current
  // value differs from it. Resetting writes the default through the same binding + markDirty, so it
  // behaves exactly like a user edit (any reactive cross-field validation re-runs on its own).
  const panel = usePrefPanelMembership(() => path);
  const defaultValue = $derived(meta?.default);
  // Inside a panel the group reset owns it — hide the per-field dot.
  const canReset = $derived(
    !panel.inPanel && typeof defaultValue === 'number' && value !== defaultValue
  );
  function resetToDefault() {
    if (typeof defaultValue !== 'number') return;
    value = defaultValue;
    ctrl.markDirty();
  }
</script>

{#if vis.visible}
  <FormField label={resolvedLabel} {hint} hintTooltip anchor={path} showReset={canReset} onReset={resetToDefault} class={className}>
    <input
      type="number"
      min={bounds.min}
      max={bounds.max}
      step={bounds.step}
      class={inputClass}
      bind:value
      {disabled}
      oninput={ctrl.markDirty}
    />
  </FormField>
{/if}
