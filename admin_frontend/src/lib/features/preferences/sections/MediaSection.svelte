<script lang="ts">
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    modalityKeys,
    modalityLabels
  } from '$lib/features/preferences/shared/preferences-constants';
  import {
    ADMIN_SECTION_CARD_MUTED,
    PREFERENCE_SECTION_SCROLL_MT
  } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<section id="preferences-media" class="{PREFERENCE_SECTION_SCROLL_MT} grid gap-4 border-b pb-6">
  <div>
    <h3 class="font-sans text-xl font-semibold text-foreground">
      {ctrl.sectionLabel('media', 'Media')}
    </h3>
    <p class="mt-1 text-sm text-muted-foreground">{ctrl.sectionDescription('media')}</p>
  </div>

  {#if ctrl.draft}
    <div class="grid gap-4 lg:grid-cols-2">
      <div class="grid gap-3 {ADMIN_SECTION_CARD_MUTED}">
        <h4 class="font-sans text-base font-semibold text-foreground">Input modalities</h4>
        {#each modalityKeys as key (key)}
          <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
            <input
              type="checkbox"
              bind:checked={ctrl.draft.media.input[key]}
              onchange={ctrl.markDirty}
            />
            <span class="font-sans text-sm font-medium">{modalityLabels[key]}</span>
          </label>
        {/each}
      </div>
      <div class="grid gap-3 {ADMIN_SECTION_CARD_MUTED}">
        <h4 class="font-sans text-base font-semibold text-foreground">Output modalities</h4>
        {#each modalityKeys as key (key)}
          <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
            <input
              type="checkbox"
              bind:checked={ctrl.draft.media.output[key]}
              onchange={ctrl.markDirty}
            />
            <span class="font-sans text-sm font-medium">{modalityLabels[key]}</span>
          </label>
        {/each}
      </div>
    </div>
  {/if}
</section>
