<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type TuningProfileScope = 'llm' | 'memory' | 'knowledge';

  type Props = {
    ctrl: PreferencesController;
    label: string;
    hint?: string;
    /** When set, writes via `ctrl.setDefaultTuningProfile` instead of `value`. */
    value?: string;
    scope?: TuningProfileScope;
    class?: string;
  };

  let {
    ctrl,
    label,
    hint = '',
    value = $bindable(''),
    scope,
    class: className = ''
  }: Props = $props();

  // `$bindable` lets callers use either `bind:value` (draft field) or one-way `value` + `scope`.

  function handleChange(event: Event) {
    const next = (event.currentTarget as HTMLSelectElement).value;
    if (scope) {
      ctrl.setDefaultTuningProfile(scope, next);
      return;
    }
    value = next;
    ctrl.markDirty();
  }
</script>

<FormField {label} {hint} class={className}>
  <select class={ADMIN_SELECT_LG} {value} onchange={handleChange}>
    {#each ctrl.profileEntries as [id, profile] (id)}
      <option value={id}>{profile.label}</option>
    {/each}
  </select>
</FormField>
