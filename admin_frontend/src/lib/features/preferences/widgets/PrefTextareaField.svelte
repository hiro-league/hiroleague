<script lang="ts">
  /**
   * Multi-line text preference, schema-driven via the shared `usePrefField` rune (label / hint /
   * advanced-visibility / reset / value all come from `path`). Replaces the hand-rolled
   * `FormField` + `preferenceFieldMeta`/`preferenceTitle`/`preferenceHint` + reset-dot boilerplate
   * that raw `<textarea>` cards (e.g. graph extraction instructions) used to repeat inline.
   */
  import FormField from '$lib/components/ui/form-field.svelte';
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

  const field = usePrefField<string>(() => ctrl, () => path, {
    label: () => label,
    hint: () => hintOverride
  });

  const TEXTAREA_CLASS =
    'w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring';
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
    <textarea
      class={TEXTAREA_CLASS}
      {rows}
      {maxlength}
      {placeholder}
      bind:value={field.value}
      {disabled}
    ></textarea>
  </FormField>
{/if}
