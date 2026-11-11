<script lang="ts">
  import { Input } from '$kit/components/ui/input/index.js';
  import Field from '$kit/ui/field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { usePrefField } from '$lib/features/preferences/shared/preferences-field.svelte';
  import {
    preferenceNumberBounds,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
    class?: string;
    disabled?: boolean;
    /** Optional override of the schema description (rare card-local copy). */
    hint?: string;
  };

  let {
    ctrl,
    path,
    label,
    class: className = '',
    disabled = false,
    hint: hintOverride
  }: Props = $props();

  // The value is owned by `path` (read/written through the schema), so the call site no longer passes
  // a `bind:value` — see preferences-field.svelte.ts. Reset/label/hint/visibility come from the rune.
  const field = usePrefField<number>(() => ctrl, () => path, {
    label: () => label,
    hint: () => hintOverride
  });
  const uid = $props.id();
  const bounds = $derived(preferenceNumberBounds(field.meta));
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
      type="number"
      min={bounds.min}
      max={bounds.max}
      step={bounds.step}
      bind:value={field.value}
      {disabled}
    />
  </Field>
{/if}
