<script lang="ts">
  import { Input } from '$kit/components/ui/input/index.js';
  import Field from '$kit/ui/field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { usePrefField } from '$lib/features/preferences/shared/preferences-field.svelte';
  import { type PreferencePath } from '$lib/features/preferences/shared/preferences-schema';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
    class?: string;
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
    disabled = false,
    placeholder,
    maxlength,
    hint: hintOverride
  }: Props = $props();

  // Value owned by `path`. The rune's null/empty normalization keeps a nullable-string field (e.g.
  // `device`) from showing a reset dot when its box is merely empty; reset still writes the real
  // default. See preferences-field.svelte.ts.
  const uid = $props.id();
  const field = usePrefField<string | null>(() => ctrl, () => path, {
    label: () => label,
    hint: () => hintOverride
  });
</script>

{#if field.visible}
  <Field
    label={field.label}
    for="{uid}-input"
    help={field.hint}
    anchor={path}
    onreset={field.canReset ? field.reset : undefined}
    class={className}
  >
    <Input
      id="{uid}-input"
      type="text"
      bind:value={field.value}
      {disabled}
      {placeholder}
      {maxlength}
    />
  </Field>
{/if}
