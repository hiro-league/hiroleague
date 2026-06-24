<script lang="ts">
  import { afterNavigate } from '$app/navigation';
  import { onMount } from 'svelte';
  import { FolderPlus, Library, MessageCircleQuestion } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
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
  } as const satisfies Record<KnowledgeTabId, AdminTabDescriptor<KnowledgeTabId>['icon']>;

  const tabDescriptors: readonly AdminTabDescriptor<KnowledgeTabId>[] = KNOWLEDGE_TABS.map(
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

<AdminPageHeader
  kicker="Knowledge base"
  title="Knowledge"
  subtitle="Markdown ingest and vector search"
  sticky
>
  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel="Knowledge sections"
      tabs={tabDescriptors}
      active={tabPrefs.activeTab}
      onSelect={(id) => {
        void tabPrefs.setActiveTab(id);
      }}
    />
  {/snippet}

  {#if ctl.error}
    <InlineDestructiveAlert message={ctl.error} />
  {/if}

  <LiveDegradedBanner />

  {#if tabPrefs.activeTab === 'ingest'}
    <KnowledgeIngestPanel {ctl} />
  {:else if tabPrefs.activeTab === 'browse'}
    <KnowledgeBrowsePanel {ctl} />
  {:else}
    <KnowledgeAskPanel {ctl} />
  {/if}
</AdminPageHeader>
