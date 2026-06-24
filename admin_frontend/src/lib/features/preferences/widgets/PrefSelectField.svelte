<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    assertPrefSelectOptionsMatchEnum,
    normalizePrefSelectOptions,
    type PrefSelectOption
  } from '$lib/features/preferences/shared/preferences-field-options';
  import { preferenceFieldMeta, preferenceHint } from '$lib/features/preferences/shared/preferences-schema';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
    path: string;
    label: string;
    value?: string;
    options: PrefSelectOption[] | Record<string, string>;
    class?: string;
    /** Overrides schema description until copy is backend-owned (#5). */
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
  const hint = $derived(hintOverride ?? preferenceHint(meta));
  const resolvedOptions = $derived.by(() => {
    const normalized = normalizePrefSelectOptions(options);
    assertPrefSelectOptionsMatchEnum(meta, normalized);
    return normalized;
  });
</script>

<FormField {label} {hint} class={className}>
  <select class={ADMIN_SELECT_LG} bind:value onchange={ctrl.markDirty}>
    {#each resolvedOptions as option (option.value)}
      <option value={option.value} disabled={option.disabled} title={option.title}>
        {option.label}
      </option>
    {/each}
  </select>
</FormField>
