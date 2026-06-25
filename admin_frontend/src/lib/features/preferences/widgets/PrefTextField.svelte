<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    preferenceFieldMeta,
    preferenceHint,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    label: string;
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
  const hint = $derived(hintOverride ?? preferenceHint(meta));
</script>

<FormField {label} {hint} hintTooltip class={className}>
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
