<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { usePrefField } from '$lib/features/preferences/shared/preferences-field.svelte';
  import { type PreferencePath } from '$lib/features/preferences/shared/preferences-schema';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
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
    class: className = '',
    inputClass = ADMIN_SELECT_LG,
    disabled = false,
    placeholder,
    maxlength,
    hint: hintOverride
  }: Props = $props();

  // Value owned by `path`. The rune's null/empty normalization keeps a nullable-string field (e.g.
  // `device`) from showing a reset dot when its box is merely empty; reset still writes the real
  // default. See preferences-field.svelte.ts.
  const field = usePrefField<string | null>(() => ctrl, () => path, {
    label: () => label,
    hint: () => hintOverride
  });
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
      type="text"
      class={inputClass}
      bind:value={field.value}
      {disabled}
      {placeholder}
      {maxlength}
    />
  </FormField>
{/if}
