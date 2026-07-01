<script lang="ts">
  /**
   * Generic tab panel for a manifest-driven preferences tab. Replaces the five near-identical
   * `*Section.svelte` wrappers: the tabpanel shell + intro + `{#each manifest.cards}` loop were
   * duplicated verbatim, so they're centralized here and every per-tab difference (label, intro,
   * header action, manifest) comes from the tab's `PrefTabDescriptor` in `preferences-tabs.ts`.
   */
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import type { PrefTabDescriptor } from '$lib/features/preferences/shared/preferences-tabs';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import PrefManifestCard from './PrefManifestCard.svelte';
  import KnowledgeBrowseLink from '$lib/features/preferences/widgets/KnowledgeBrowseLink.svelte';

  let { ctrl, tab }: { ctrl: PreferencesController; tab: PrefTabDescriptor } = $props();

  // Intro is either a static string or a live section description resolved through the controller.
  const introText = $derived(
    tab.intro ? ('text' in tab.intro ? tab.intro.text : ctrl.sectionDescription(tab.intro.sectionKey)) : ''
  );
</script>

<div
  id={PREFERENCE_TAB_PANEL_IDS[tab.id]}
  class="grid min-w-0 grid-cols-1 gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS[tab.id]}
>
  {#if tab.headerAction === 'knowledgeBrowse'}
    <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      {#if introText}
        <p class="min-w-0 flex-1 text-sm text-muted-foreground">{introText}</p>
      {/if}
      <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
        <KnowledgeBrowseLink busy={ctrl.busy} />
      </div>
    </div>
  {:else if introText}
    <p class="text-sm text-muted-foreground">{introText}</p>
  {/if}

  <!-- Cards + fields are data-driven from the tab's manifest (manifest rollout). Order, sections, and
       the search index all derive from the same manifest — see preferences-tabs.ts. -->
  {#if ctrl.draft && tab.manifest}
    {#each tab.manifest.cards as card (card.id)}
      <PrefManifestCard {ctrl} {card} />
    {/each}
  {/if}
</div>
