<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { preferenceFieldMeta, preferenceHint } from '$lib/features/preferences/shared/preferences-schema';
  import SettingToggle from '$lib/features/preferences/widgets/SettingToggle.svelte';

  type Props = {
    ctrl: PreferencesController;
    path: string;
    label: string;
    checked?: boolean;
    disabled?: boolean;
    class?: string;
    /** Overrides schema description until copy is backend-owned (#5). */
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
  const showDetails = $derived(Boolean(details) || Boolean(hintText));
</script>

{#if showDetails}
  <SettingToggle {label} bind:checked {disabled} class={className} onchange={ctrl.markDirty}>
    {#snippet details()}
      {#if details}
        {@render details()}
      {:else}
        {hintText}
      {/if}
    {/snippet}
  </SettingToggle>
{:else}
  <SettingToggle {label} bind:checked {disabled} class={className} onchange={ctrl.markDirty} />
{/if}
