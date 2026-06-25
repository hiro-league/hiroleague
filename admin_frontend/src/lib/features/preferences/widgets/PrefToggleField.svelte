<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    preferenceFieldMeta,
    preferenceHint,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import SettingToggle from '$lib/features/preferences/widgets/SettingToggle.svelte';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    label: string;
    checked?: boolean;
    disabled?: boolean;
    class?: string;
    /** Optional override of the schema description (rare card-local copy). */
    hint?: string;
    /** Custom details body (e.g. eval toggles with inline code). */
    details?: Snippet;
  };

  let {
    ctrl,
    path,
    label,
    checked = $bindable(false),
    disabled = false,
    class: className = '',
    hint: hintOverride,
    details
  }: Props = $props();

  const meta = $derived(preferenceFieldMeta(ctrl.fieldSchema, path));
  const hintText = $derived(hintOverride ?? preferenceHint(meta));
</script>

<SettingToggle
  {label}
  hint={hintText}
  {details}
  bind:checked
  {disabled}
  class={className}
  onchange={ctrl.markDirty}
/>
