<script lang="ts">
  import { afterNavigate } from '$app/navigation';
  import { onMount } from 'svelte';
  import { FolderPlus, Library, MessageCircleQuestion } from '@lucide/svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import PageTabs from '$kit/ui/page-tabs.svelte';
  import type { PageTab } from '$kit/ui/page-tabs.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import { createKnowledgePreferences } from '$lib/preferences/knowledge-preferences.svelte';
  import KnowledgeAskPanel from './ask/KnowledgeAskPanel.svelte';
  import KnowledgeBrowsePanel from './browse/KnowledgeBrowsePanel.svelte';
  import KnowledgeIngestPanel from './ingest/KnowledgeIngestPanel.svelte';
  import { KNOWLEDGE_TABS, type KnowledgeTabId } from './shared/knowledge-pure';
  import { createKnowledgePageController } from './state/knowledge-controller.svelte';
  import LiveDegradedBanner from '$lib/live/LiveDegradedBanner.svelte';

  /** Thin composition root: delegates orchestration to `state/knowledge-controller.svelte.ts`. */
  const tabPrefs = createKnowledgePreferences();
  const ctl = createKnowledgePageController(tabPrefs);

  onMount(() => {
    tabPrefs.initialize();
    return ctl.mount();
  });

  afterNavigate(() => {
    tabPrefs.syncActiveTabFromUrl();
  });

  const knowledgeTabIcons = {
    ingest: FolderPlus,
    browse: Library,
    ask: MessageCircleQuestion
  } as const satisfies Record<KnowledgeTabId, PageTab<KnowledgeTabId>['icon']>;

  const tabDescriptors: readonly PageTab<KnowledgeTabId>[] = KNOWLEDGE_TABS.map(
    (tab) => ({
      id: tab.id,
      label: tab.label,
      kind: 'pane' as const,
      icon: knowledgeTabIcons[tab.id]
    })
  );
</script>

<svelte:head>
  <title>Knowledge - Hiro Admin</title>
</svelte:head>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Knowledge" description="Markdown ingest and vector search">
    {#snippet tabs()}
    <PageTabs
      label="Knowledge sections"
      tabs={tabDescriptors}
      value={tabPrefs.activeTab}
      onchange={(id) => {
        void tabPrefs.setActiveTab(id);
      }}
    />
    {/snippet}
  </PageHeader>
  

  {#if ctl.error}
    <Notice message={ctl.error} />
  {/if}

  <LiveDegradedBanner />

  {#if tabPrefs.activeTab === 'ingest'}
    <KnowledgeIngestPanel {ctl} />
  {:else if tabPrefs.activeTab === 'browse'}
    <KnowledgeBrowsePanel {ctl} />
  {:else}
    <KnowledgeAskPanel {ctl} />
  {/if}
</section>
