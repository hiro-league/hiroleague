<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    assertPrefSelectOptionsMatchEnum,
    normalizePrefSelectOptions,
    type PrefSelectOption
  } from '$lib/features/preferences/shared/preferences-field-options';
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
    value?: string;
    options: PrefSelectOption[] | Record<string, string>;
    class?: string;
    /** Optional override of the schema description (rare card-local copy). */
    hint?: string;
  };

  let {
    ctrl,
    path,
    label,
    value = $bindable(),
    options,
    class: className = '',
    hint: hintOverride
  }: Props = $props();

  const meta = $derived(preferenceFieldMeta(ctrl.fieldSchema, path));
  const resolvedLabel = $derived(label ?? preferenceTitle(meta) ?? path);
  const hint = $derived(hintOverride ?? preferenceHint(meta));
  const resolvedOptions = $derived.by(() => {
    const normalized = normalizePrefSelectOptions(options);
    assertPrefSelectOptionsMatchEnum(meta, normalized);
    return normalized;
  });
  const vis = usePrefFieldVisibility(() => preferenceIsAdvanced(meta));

  // "Reset to default" affordance: only when the schema carries a string (enum) default and the
  // current value differs. Resetting goes through the same binding + markDirty as a user pick, so
  // any UI reaction to the value change (e.g. cross-field gating) re-runs on its own.
  const panel = usePrefPanelMembership(() => path);
  const defaultValue = $derived(meta?.default);
  // Inside a panel the group reset owns it — hide the per-field dot.
  const canReset = $derived(
    !panel.inPanel && typeof defaultValue === 'string' && value !== defaultValue
  );
  function resetToDefault() {
    if (typeof defaultValue !== 'string') return;
    value = defaultValue;
    ctrl.markDirty();
  }
</script>

{#if vis.visible}
  <FormField label={resolvedLabel} {hint} hintTooltip anchor={path} showReset={canReset} onReset={resetToDefault} class={className}>
    <select class={ADMIN_SELECT_LG} bind:value onchange={ctrl.markDirty}>
      {#each resolvedOptions as option (option.value)}
        <option value={option.value} disabled={option.disabled} title={option.title}>
          {option.label}
        </option>
      {/each}
    </select>
  </FormField>
{/if}
