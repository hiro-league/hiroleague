<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { FileText, Plus, Search, Settings2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import KnowledgeAskPanel from './ask/KnowledgeAskPanel.svelte';
  import KnowledgeBrowsePanel from './browse/KnowledgeBrowsePanel.svelte';
  import KnowledgeIngestPanel from './ingest/KnowledgeIngestPanel.svelte';
  import {
    KNOWLEDGE_PREFERENCES_SECTION_HREF,
    KNOWLEDGE_TABS,
    type KnowledgeTabId
  } from './shared/knowledge-pure';
  import {
    cnKnowledgeTab,
    KNOWLEDGE_HEADER_INTRO,
    KNOWLEDGE_HEADER_KICKER,
    KNOWLEDGE_HEADER_TITLE,
    KNOWLEDGE_PAGE_STICKY_HEADER,
    KNOWLEDGE_TABLIST_SHELL
  } from './shared/knowledge-ui';
  import { createKnowledgePageController } from './state/knowledge-controller.svelte';
  import { cn } from '$lib/utils';

  /** Thin composition root: delegates orchestration to `state/knowledge-controller.svelte.ts`. */
  const ctl = createKnowledgePageController();
  onMount(ctl.mount);

  const TAB_ICONS: Record<KnowledgeTabId, typeof Plus> = {
    ingest: Plus,
    browse: FileText,
    ask: Search
  };
</script>

<svelte:head>
  <title>Knowledge - Hiro Admin</title>
</svelte:head>

<div class="grid max-w-[1420px] gap-5">
  <section class={cn('grid gap-3', KNOWLEDGE_PAGE_STICKY_HEADER)}>
    <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div>
        <p class={KNOWLEDGE_HEADER_KICKER}>Knowledge base</p>
        <h2 class={KNOWLEDGE_HEADER_TITLE}>Knowledge</h2>
        <p class={KNOWLEDGE_HEADER_INTRO}>Markdown ingest and vector search</p>
      </div>
      <div class={KNOWLEDGE_TABLIST_SHELL} role="tablist" aria-label="Knowledge sections">
        {#each KNOWLEDGE_TABS as tab (tab.id)}
          {@const TabIcon = TAB_ICONS[tab.id]}
          <Button
            class={cn(cnKnowledgeTab(ctl.activeTab === tab.id), 'gap-1.5')}
            variant={ctl.activeTab === tab.id ? 'secondary' : 'ghost'}
            role="tab"
            aria-selected={ctl.activeTab === tab.id}
            onclick={() => {
              void ctl.setActiveTab(tab.id);
            }}
          >
            <TabIcon size={16} aria-hidden="true" />
            {tab.label}
          </Button>
        {/each}
        <Button
          class={cn(cnKnowledgeTab(false), 'gap-1.5')}
          variant="ghost"
          title="Open workspace knowledge preferences"
          onclick={() => void goto(KNOWLEDGE_PREFERENCES_SECTION_HREF)}
        >
          <Settings2 size={16} aria-hidden="true" />
          Preferences
        </Button>
      </div>
    </div>
    {#if ctl.error}
      <div class="rounded-md border border-destructive/35 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive">
        {ctl.error}
      </div>
    {/if}
  </section>

  {#if ctl.activeTab === 'ingest'}
    <KnowledgeIngestPanel {ctl} />
  {:else if ctl.activeTab === 'browse'}
    <KnowledgeBrowsePanel {ctl} />
  {:else}
    <KnowledgeAskPanel {ctl} />
  {/if}
</div>
