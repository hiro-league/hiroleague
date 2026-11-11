<script lang="ts">
  /**
   * Multi-line text preference, schema-driven via the shared `usePrefField` rune (label / hint /
   * advanced-visibility / reset / value all come from `path`). Replaces the hand-rolled
   * `Field` + `preferenceFieldMeta`/`preferenceTitle`/`preferenceHint` + reset-dot boilerplate
   * that raw `<textarea>` cards (e.g. graph extraction instructions) used to repeat inline.
   */
  import { Textarea } from '$kit/components/ui/textarea/index.js';
  import Field from '$kit/ui/field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { usePrefField } from '$lib/features/preferences/shared/preferences-field.svelte';
  import { type PreferencePath } from '$lib/features/preferences/shared/preferences-schema';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
    rows?: number;
    maxlength?: number;
    placeholder?: string;
    class?: string;
    disabled?: boolean;
    /** Optional override of the schema description (rare card-local copy). */
    hint?: string;
  };

  let {
    ctrl,
    path,
    label,
    rows = 6,
    maxlength,
    placeholder,
    class: className = '',
    disabled = false,
    hint: hintOverride
  }: Props = $props();

  const uid = $props.id();
  const field = usePrefField<string>(() => ctrl, () => path, {
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
    <Textarea
      id="{uid}-input"
      {rows}
      {maxlength}
      {placeholder}
      bind:value={field.value}
      {disabled}
    />
  </Field>
{/if}
