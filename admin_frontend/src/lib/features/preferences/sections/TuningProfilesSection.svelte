<script lang="ts">
  import { Plus, RotateCcw, Trash2 } from '@lucide/svelte';
  import type { TuningProfile } from '$lib/api/preferences';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { tuningProfileSectionBodyId } from '$lib/features/preferences/shared/preferences-section-a11y';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  // Card-local hint: `num_ctx` is a dynamic per-profile key (tuning_profiles.*), not a flat
  // schema-map field, so its copy can't live on a backend `Field(description=...)` like the rest.
  const CONTEXT_WINDOW_HINT =
    'Local providers only (Ollama num_ctx). Blank = provider default (Ollama: 2048). ' +
    "Don't set to the full model window — large values use a lot of memory.";

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

<div
  id={PREFERENCE_TAB_PANEL_IDS['tuning-profiles']}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS['tuning-profiles']}
>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    <p class="min-w-0 flex-1 text-sm text-muted-foreground">
      Temperature, max tokens, thinking, and context-window presets referenced by the chat and memory defaults above.
    </p>
    {#if ctrl.draft}
      <Button
        variant="outline"
        size="sm"
        class="shrink-0"
        disabled={ctrl.busy}
        onclick={ctrl.createProfile}
      >
        <Plus size={14} /> Add profile
      </Button>
    {/if}
  </div>

  {#if ctrl.draft}
    <div class="grid gap-3">
      {#each profileDisplayEntries as [id, profile] (id)}
        <SectionCardMuted
          title={profile.label.trim() || id}
          description={profile.locked ? 'Built-in profile — reset restores defaults.' : undefined}
          collapsible
          bodyId={tuningProfileSectionBodyId(id)}
        >
          {#snippet headerActions()}
            {#if profile.locked}
              <Button
                variant="outline"
                size="sm"
                disabled={ctrl.busy}
                onclick={() => ctrl.resetLockedProfile(id)}
              >
                <RotateCcw size={14} /> Reset
              </Button>
            {:else}
              <Button
                variant="destructive"
                size="sm"
                disabled={ctrl.busy}
                onclick={() => ctrl.deleteProfile(id)}
              >
                <Trash2 size={14} /> Delete
              </Button>
            {/if}
          {/snippet}
          <FormField label="Name" class="max-w-md">
            <input
              class={ADMIN_SELECT_LG}
              data-profile-name-edit="true"
              value={profile.label}
              onfocus={() => onProfileNameFocus(id)}
              onblur={onProfileNameBlur}
              oninput={(event) => ctrl.updateProfile(id, 'label', event.currentTarget.value)}
            />
          </FormField>
          <div class="grid gap-3 md:grid-cols-3">
            <FormField label="Temperature">
              <input
                type="number"
                min="0"
                max="2"
                step="0.1"
                class={ADMIN_SELECT_LG}
                value={profile.temperature}
                oninput={(event) => ctrl.updateProfile(id, 'temperature', event.currentTarget.value)}
              />
            </FormField>
            <FormField label="Max tokens">
              <input
                type="number"
                min="1"
                step="1"
                class={ADMIN_SELECT_LG}
                value={profile.max_tokens}
                oninput={(event) => ctrl.updateProfile(id, 'max_tokens', event.currentTarget.value)}
              />
            </FormField>
            <FormField label="Thinking">
              <select
                class={ADMIN_SELECT_LG}
                value={profile.thinking ?? 'default'}
                onchange={(event) => ctrl.updateProfile(id, 'thinking', event.currentTarget.value)}
              >
                <option value="default">Model default</option>
                <option value="off">Off</option>
                <option value="minimal">Minimal</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </FormField>
            <FormField
              label="Context window"
              hint={CONTEXT_WINDOW_HINT}
            >
              <input
                type="number"
                min="1"
                step="1"
                class={ADMIN_SELECT_LG}
                placeholder="Provider default"
                value={profile.num_ctx ?? ''}
                oninput={(event) => ctrl.updateProfile(id, 'num_ctx', event.currentTarget.value)}
              />
            </FormField>
          </div>
        </SectionCardMuted>
      {/each}
    </div>
  {/if}
</div>
