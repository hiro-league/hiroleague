<script lang="ts">
  import PickSelect from '$kit/ui/pick-select.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    assertPrefSelectOptionsMatchEnum,
    normalizePrefSelectOptions,
    type PrefSelectOption
  } from '$lib/features/preferences/shared/preferences-field-options';
  import { usePrefField } from '$lib/features/preferences/shared/preferences-field.svelte';
  import { type PreferencePath } from '$lib/features/preferences/shared/preferences-schema';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
    options: PrefSelectOption[] | Record<string, string>;
    class?: string;
    /** Optional override of the schema description (rare card-local copy). */
    hint?: string;
  };

  let { ctrl, path, label, options, class: className = '', hint: hintOverride }: Props = $props();

  // Value owned by `path`; options are validated against the schema enum so the picker can't drift
  // from the backend. See preferences-field.svelte.ts.
  const field = usePrefField<string>(() => ctrl, () => path, {
    label: () => label,
    hint: () => hintOverride
  });
  const resolvedOptions = $derived.by(() => {
    const normalized = normalizePrefSelectOptions(options);
    assertPrefSelectOptionsMatchEnum(field.meta, normalized);
    return normalized;
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
    <PickSelect
      class="h-10 w-full text-sm"
      label={field.label}
      value={field.value}
      options={resolvedOptions}
      onchange={(v) => (field.value = v)}
    />
  </FormField>
{/if}
