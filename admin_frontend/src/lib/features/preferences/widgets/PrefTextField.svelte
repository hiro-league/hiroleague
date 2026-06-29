<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { usePrefFieldVisibility } from '$lib/features/preferences/shared/preferences-advanced.svelte';
  import { usePrefPanelMembership } from '$lib/features/preferences/shared/preferences-panel.svelte';
  import {
    preferenceFieldMeta,
    preferenceHint,
    preferenceIsAdvanced,
    preferenceTitle,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
    value?: string | null;
    class?: string;
    inputClass?: string;
    disabled?: boolean;
    placeholder?: string;
    maxlength?: number;
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
    placeholder,
    maxlength,
    hint: hintOverride
  }: Props = $props();

  const meta = $derived(preferenceFieldMeta(ctrl.fieldSchema, path));
  const resolvedLabel = $derived(label ?? preferenceTitle(meta) ?? path);
  const hint = $derived(hintOverride ?? preferenceHint(meta));
  const vis = usePrefFieldVisibility(() => preferenceIsAdvanced(meta));

  // "Reset to default" affordance. Text defaults may be a string OR null (nullable fields like
  // `device`); normalize null/undefined → "" for the *comparison* so a null-default field whose box
  // is merely empty shows no dot, while reset still writes the real default value.
  const panel = usePrefPanelMembership(() => path);
  const defaultValue = $derived(meta?.default);
  const norm = (v: unknown) => (v == null ? '' : v);
  // Inside a panel the group reset owns it — hide the per-field dot.
  const canReset = $derived(
    !panel.inPanel &&
      (typeof defaultValue === 'string' || defaultValue === null) &&
      norm(value) !== norm(defaultValue)
  );
  function resetToDefault() {
    if (typeof defaultValue !== 'string' && defaultValue !== null) return;
    value = defaultValue;
    ctrl.markDirty();
  }
</script>

{#if vis.visible}
  <FormField label={resolvedLabel} {hint} hintTooltip anchor={path} showReset={canReset} onReset={resetToDefault} class={className}>
    <input
      type="text"
      class={inputClass}
      bind:value
      {disabled}
      {placeholder}
      {maxlength}
      oninput={ctrl.markDirty}
    />
  </FormField>
{/if}
