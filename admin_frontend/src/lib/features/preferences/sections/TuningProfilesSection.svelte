<script lang="ts">
  import { Plus, RotateCcw, Trash2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { TUNING_PROFILES_SECTION_ID } from '$lib/features/preferences/state/preferences-section-nav';
  import {
    ADMIN_SECTION_CARD_MUTED,
    ADMIN_SELECT_LG,
    PREFERENCE_SECTION_SCROLL_MT
  } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<section id={TUNING_PROFILES_SECTION_ID} class="{PREFERENCE_SECTION_SCROLL_MT} grid gap-4">
  <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
    <div>
      <h3 class="font-sans text-xl font-semibold text-foreground">Tuning profiles</h3>
      <p class="mt-1 text-sm text-muted-foreground">
        Temperature, max tokens, and thinking presets referenced by the chat and memory defaults above.
      </p>
    </div>
    <Button variant="outline" size="sm" disabled={ctrl.busy} onclick={ctrl.createProfile}>
      <Plus size={14} /> Add profile
    </Button>
  </div>

  <div class="grid gap-3 {ADMIN_SECTION_CARD_MUTED}">
    <div class="grid gap-3">
      {#each ctrl.profileEntries as [id, profile] (id)}
        <div class="grid gap-3 rounded-md border border-border/60 bg-card/45 p-3">
          <div class="flex flex-col gap-2 sm:flex-row sm:items-end">
            <FormField label="Name" class="flex-1">
              <input
                class={ADMIN_SELECT_LG}
                value={profile.label}
                oninput={(event) => ctrl.updateProfile(id, 'label', event.currentTarget.value)}
              />
            </FormField>
            <div class="flex gap-2">
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
            </div>
          </div>
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
          </div>
        </div>
      {/each}
    </div>
  </div>
</section>
