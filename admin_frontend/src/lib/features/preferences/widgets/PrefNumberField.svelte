<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { usePrefField } from '$lib/features/preferences/shared/preferences-field.svelte';
  import {
    preferenceNumberBounds,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
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
    class: className = '',
    inputClass = ADMIN_SELECT_LG,
    disabled = false,
    hint: hintOverride
  }: Props = $props();

  // The value is owned by `path` (read/written through the schema), so the call site no longer passes
  // a `bind:value` — see preferences-field.svelte.ts. Reset/label/hint/visibility come from the rune.
  const field = usePrefField<number>(() => ctrl, () => path, {
    label: () => label,
    hint: () => hintOverride
  });
  const bounds = $derived(preferenceNumberBounds(field.meta));
</script>

{#if field.visible}
  <FormField
    label={field.label}
    hint={field.hint}
    hintTooltip
    anchor={path}
    showReset={field.canReset}
    onReset={field.reset}
    class={className}
  >
    <input
      type="number"
      min={bounds.min}
      max={bounds.max}
      step={bounds.step}
      class={inputClass}
      bind:value={field.value}
      {disabled}
    />
  </FormField>
{/if}
