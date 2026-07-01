<script lang="ts">
  /**
   * One row of the Model Profiles table — inline-editable temp / thinking / max-tokens / context, plus
   * reset (locked) / duplicate / delete actions. Extracted from `TuningProfilesSection` so the section
   * keeps only the table shell, filtering, and the name-sort freeze. Edits write straight to the draft
   * via `ctrl.updateProfile` (callback props, no `bind:`), so the section owns no per-row state.
   */
  import { Copy, Lock, RotateCcw, Trash2 } from '@lucide/svelte';
  import type { TuningProfile } from '$lib/api/preferences';
  import Button from '$lib/components/ui/button.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { THINKING_SELECT_OPTIONS } from '$lib/features/preferences/shared/preferences-constants';
  import { ADMIN_SELECT_SM, ADMIN_TABLE_ROW } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: PreferencesController;
    id: string;
    profile: TuningProfile;
    /** Freeze the label sort while a name field is focused so editing doesn't steal focus. */
    onNameFocus: (id: string) => void;
    onNameBlur: () => void;
  };

  let { ctrl, id, profile, onNameFocus, onNameBlur }: Props = $props();
</script>

<tr class={ADMIN_TABLE_ROW}>
  <td class="px-3 py-1.5">
    <div class="flex items-center gap-2">
      {#if profile.locked}
        <Lock size={13} class="shrink-0 text-muted-foreground" aria-hidden="true" />
      {/if}
      <input
        class={cn(ADMIN_SELECT_SM, 'w-full min-w-[10rem]')}
        data-profile-name-edit="true"
        aria-label="Profile name"
        value={profile.label}
        onfocus={() => onNameFocus(id)}
        onblur={onNameBlur}
        oninput={(event) => ctrl.updateProfile(id, 'label', event.currentTarget.value)}
      />
    </div>
  </td>
  <td class="px-3 py-1.5">
    <input
      type="number"
      min="0"
      max="2"
      step="0.1"
      aria-label="Temperature"
      class={cn(ADMIN_SELECT_SM, 'w-20')}
      value={profile.temperature}
      oninput={(event) => ctrl.updateProfile(id, 'temperature', event.currentTarget.value)}
    />
  </td>
  <td class="px-3 py-1.5">
    <select
      aria-label="Thinking"
      class={cn(ADMIN_SELECT_SM, 'w-full')}
      value={profile.thinking ?? 'default'}
      onchange={(event) => ctrl.updateProfile(id, 'thinking', event.currentTarget.value)}
    >
      {#each THINKING_SELECT_OPTIONS as option (option.value)}
        <option value={option.value}>{option.label}</option>
      {/each}
    </select>
  </td>
  <td class="px-3 py-1.5">
    <input
      type="number"
      min="1"
      step="1"
      aria-label="Max tokens"
      class={cn(ADMIN_SELECT_SM, 'w-24')}
      value={profile.max_tokens}
      oninput={(event) => ctrl.updateProfile(id, 'max_tokens', event.currentTarget.value)}
    />
  </td>
  <td class="px-3 py-1.5">
    <input
      type="number"
      min="1"
      step="1"
      aria-label="Context window"
      placeholder="Default"
      class={cn(ADMIN_SELECT_SM, 'w-28')}
      value={profile.num_ctx ?? ''}
      oninput={(event) => ctrl.updateProfile(id, 'num_ctx', event.currentTarget.value)}
    />
  </td>
  <td class="px-3 py-1.5">
    <div class="flex items-center justify-end gap-1">
      {#if profile.locked}
        <Button
          variant="ghost"
          size="icon"
          class="size-8"
          title="Reset to default"
          aria-label="Reset to default"
          disabled={ctrl.busy}
          onclick={() => ctrl.resetLockedProfile(id)}
        >
          <RotateCcw size={14} />
        </Button>
      {/if}
      <Button
        variant="ghost"
        size="icon"
        class="size-8"
        title="Duplicate to a custom profile"
        aria-label="Duplicate to a custom profile"
        disabled={ctrl.busy}
        onclick={() => ctrl.duplicateProfile(id)}
      >
        <Copy size={14} />
      </Button>
      {#if !profile.locked}
        <Button
          variant="ghost"
          size="icon"
          class="size-8 text-destructive hover:text-destructive"
          title="Delete"
          aria-label="Delete"
          disabled={ctrl.busy}
          onclick={() => ctrl.deleteProfile(id)}
        >
          <Trash2 size={14} />
        </Button>
      {/if}
    </div>
  </td>
</tr>
