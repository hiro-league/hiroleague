<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    preferenceFieldMeta,
    preferenceHint,
    preferenceNumberBounds
  } from '$lib/features/preferences/shared/preferences-schema';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
    path: string;
    label: string;
    value?: number;
    class?: string;
    inputClass?: string;
    disabled?: boolean;
    /** Overrides schema description until copy is backend-owned (#5). */
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
  const bounds = $derived(preferenceNumberBounds(meta));
  const hint = $derived(hintOverride ?? preferenceHint(meta));
</script>

<FormField {label} {hint} class={className}>
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
