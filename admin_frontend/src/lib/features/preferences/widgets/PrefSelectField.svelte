<script lang="ts">
  import PickSelect from '$kit/ui/pick-select.svelte';
  import Field from '$kit/ui/field.svelte';
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
  const uid = $props.id();
  const resolvedOptions = $derived.by(() => {
    const normalized = normalizePrefSelectOptions(options);
    assertPrefSelectOptionsMatchEnum(field.meta, normalized);
    return normalized;
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
    <PickSelect
      id="{uid}-input"
      class="h-10 w-full text-sm"
      label={field.label}
      value={field.value}
      options={resolvedOptions}
      onchange={(v) => (field.value = v)}
    />
  </Field>
{/if}
