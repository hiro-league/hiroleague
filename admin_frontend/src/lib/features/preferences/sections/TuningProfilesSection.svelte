<script lang="ts">
  import { Info, Plus, Search } from '@lucide/svelte';
  import type { TuningProfile } from '$lib/api/preferences';
  import Button from '$lib/components/ui/button.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import TuningProfileRow from '$lib/features/preferences/sections/tuning-profiles/TuningProfileRow.svelte';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import { ADMIN_SEARCH_FIELD, ADMIN_TABLE, ADMIN_TABLE_HEAD } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  // Card-local hint: `num_ctx` is a dynamic per-profile key (tuning_profiles.*), not a flat
  // schema-map field, so its copy can't live on a backend `Field(description=...)` like the rest.
  const CONTEXT_WINDOW_HINT =
    'Local providers only (Ollama num_ctx). Blank = provider default (Ollama: 2048). ' +
    "Don't set to the full model window — large values use a lot of memory.";

  let filterText = $state('');

  /** Freeze list order while a name field is focused so label sort does not steal focus. */
  let nameEditProfileId = $state<string | null>(null);
  let frozenEntryOrder = $state<string[] | null>(null);
  let wasDirty = $state(false);

  const profileDisplayEntries = $derived.by((): [string, TuningProfile][] => {
    const sorted = ctrl.profileEntries;
    if (!nameEditProfileId || !frozenEntryOrder) return sorted;

    const byId = new Map(sorted);
    return frozenEntryOrder
      .map((profileId) => {
        const profile = byId.get(profileId);
        return profile ? ([profileId, profile] as [string, TuningProfile]) : null;
      })
      .filter((entry): entry is [string, TuningProfile] => entry !== null);
  });

  // Client-side filter (label or id). Editing a profile's name never changes `filterText`, so an
  // in-progress name edit cannot filter its own row out from under the cursor.
  const filteredEntries = $derived.by((): [string, TuningProfile][] => {
    const query = filterText.trim().toLowerCase();
    if (!query) return profileDisplayEntries;
    return profileDisplayEntries.filter(
      ([id, profile]) =>
        profile.label.toLowerCase().includes(query) || id.toLowerCase().includes(query)
    );
  });

  // Built-ins (locked, code-owned, reset-restorable) first, then user-created customs.
  const builtinEntries = $derived(filteredEntries.filter(([, profile]) => profile.locked));
  const customEntries = $derived(filteredEntries.filter(([, profile]) => !profile.locked));

  function onProfileNameFocus(profileId: string) {
    nameEditProfileId = profileId;
    frozenEntryOrder = ctrl.profileEntries.map(([id]) => id);
  }

  function releaseProfileNameSortFreeze() {
    nameEditProfileId = null;
    frozenEntryOrder = null;
  }

  function onProfileNameBlur() {
    // Defer so focus moving to another profile name input does not release the freeze mid-edit.
    queueMicrotask(() => {
      const active = document.activeElement;
      if (active instanceof HTMLInputElement && active.dataset.profileNameEdit === 'true') {
        return;
      }
      releaseProfileNameSortFreeze();
    });
  }

  $effect(() => {
    if (wasDirty && !ctrl.dirty && !ctrl.busy) {
      releaseProfileNameSortFreeze();
    }
    wasDirty = ctrl.dirty;
  });
</script>

{#snippet groupHeader(label: string)}
  <tr class="bg-muted/40">
    <td
      colspan="6"
      class="px-3 py-1.5 font-sans text-xs font-bold uppercase tracking-wide text-muted-foreground"
    >
      {label}
    </td>
  </tr>
{/snippet}

<div
  id={PREFERENCE_TAB_PANEL_IDS['tuning-profiles']}
  class="grid min-w-0 grid-cols-1 gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS['tuning-profiles']}
>
  <p class="text-sm text-muted-foreground">
    Temperature, max tokens, thinking, and context-window presets referenced by the chat and memory
    defaults above. Edit a value in place; duplicate a preset to start a new custom profile.
  </p>

  {#if ctrl.draft}
    <div class="flex items-center gap-2">
      <div class={cn(ADMIN_SEARCH_FIELD, 'min-w-0 flex-1 sm:max-w-xs')}>
        <Search size={15} class="shrink-0 text-muted-foreground" aria-hidden="true" />
        <input
          class="w-full bg-transparent outline-none"
          placeholder="Filter profiles"
          aria-label="Filter profiles"
          bind:value={filterText}
        />
      </div>
      <Button
        variant="outline"
        size="sm"
        class="shrink-0"
        disabled={ctrl.busy}
        onclick={ctrl.createProfile}
      >
        <Plus size={14} /> Add profile
      </Button>
    </div>

    <div class="overflow-x-auto rounded-md border">
      <table class={cn(ADMIN_TABLE, 'min-w-[760px]')}>
        <colgroup>
          <col />
          <col class="w-24" />
          <col class="w-40" />
          <col class="w-28" />
          <col class="w-32" />
          <col class="w-28" />
        </colgroup>
        <thead class={ADMIN_TABLE_HEAD}>
          <tr>
            <th class="px-3 py-2 font-medium">Profile</th>
            <th class="px-3 py-2 font-medium">Temp</th>
            <th class="px-3 py-2 font-medium">Thinking</th>
            <th class="px-3 py-2 font-medium">Max tokens</th>
            <th class="px-3 py-2 font-medium">
              <span class="inline-flex cursor-help items-center gap-1" title={CONTEXT_WINDOW_HINT}>
                Context
                <Info size={12} class="text-muted-foreground" aria-hidden="true" />
              </span>
            </th>
            <th class="px-3 py-2"><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {#if filteredEntries.length === 0}
            <tr>
              <td colspan="6" class="px-3 py-6 text-center text-sm text-muted-foreground">
                No profiles match “{filterText}”.
              </td>
            </tr>
          {:else}
            {#if builtinEntries.length > 0}
              {@render groupHeader('Built-in')}
              {#each builtinEntries as [id, profile] (id)}
                <TuningProfileRow
                  {ctrl}
                  {id}
                  {profile}
                  onNameFocus={onProfileNameFocus}
                  onNameBlur={onProfileNameBlur}
                />
              {/each}
            {/if}
            {#if customEntries.length > 0}
              {@render groupHeader('Custom')}
              {#each customEntries as [id, profile] (id)}
                <TuningProfileRow
                  {ctrl}
                  {id}
                  {profile}
                  onNameFocus={onProfileNameFocus}
                  onNameBlur={onProfileNameBlur}
                />
              {/each}
            {/if}
          {/if}
        </tbody>
      </table>
    </div>
  {/if}
</div>
