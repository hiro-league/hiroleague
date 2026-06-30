<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { usePrefField } from '$lib/features/preferences/shared/preferences-field.svelte';
  import { type PreferencePath } from '$lib/features/preferences/shared/preferences-schema';
  import SettingToggle from '$lib/features/preferences/widgets/SettingToggle.svelte';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
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
    disabled = false,
    class: className = '',
    hint: hintOverride,
    details
  }: Props = $props();

  // Checked state owned by `path`; the rune's setter marks dirty on toggle. See
  // preferences-field.svelte.ts.
  const field = usePrefField<boolean>(() => ctrl, () => path, {
    label: () => label,
    hint: () => hintOverride
  });
</script>

{#if field.visible}
  <SettingToggle
    label={field.label}
    anchor={path}
    hint={field.hint}
    {details}
    bind:checked={field.value}
    {disabled}
    class={className}
    showReset={field.canReset}
    onReset={field.reset}
  />
{/if}
