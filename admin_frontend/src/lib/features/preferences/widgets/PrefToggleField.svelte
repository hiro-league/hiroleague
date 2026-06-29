<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { usePrefFieldVisibility } from '$lib/features/preferences/shared/preferences-advanced.svelte';
  import { usePrefPanelMembership } from '$lib/features/preferences/shared/preferences-panel.svelte';
  import {
    preferenceFieldMeta,
    preferenceHint,
    preferenceIsAdvanced,
    preferenceTitle,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import SettingToggle from '$lib/features/preferences/widgets/SettingToggle.svelte';

  type Props = {
    ctrl: PreferencesController;
    path: PreferencePath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
    checked?: boolean;
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
    checked = $bindable(false),
    disabled = false,
    class: className = '',
    hint: hintOverride,
    details
  }: Props = $props();

  const meta = $derived(preferenceFieldMeta(ctrl.fieldSchema, path));
  const resolvedLabel = $derived(label ?? preferenceTitle(meta) ?? path);
  const hintText = $derived(hintOverride ?? preferenceHint(meta));
  const vis = usePrefFieldVisibility(() => preferenceIsAdvanced(meta));

  // "Reset to default" affordance: only when the schema carries a boolean default and the current
  // checked state differs. Resetting flips `checked` through the same binding + markDirty as a user
  // toggle, so any reactive validation re-runs on its own.
  const panel = usePrefPanelMembership(() => path);
  const defaultChecked = $derived(meta?.default);
  // Inside a panel the group reset owns it — hide the per-field dot.
  const canReset = $derived(
    !panel.inPanel && typeof defaultChecked === 'boolean' && checked !== defaultChecked
  );
  function resetToDefault() {
    if (typeof defaultChecked !== 'boolean') return;
    checked = defaultChecked;
    ctrl.markDirty();
  }
</script>

{#if vis.visible}
  <SettingToggle
    label={resolvedLabel}
    anchor={path}
    hint={hintText}
    {details}
    bind:checked
    {disabled}
    class={className}
    onchange={ctrl.markDirty}
    showReset={canReset}
    onReset={resetToDefault}
  />
{/if}
