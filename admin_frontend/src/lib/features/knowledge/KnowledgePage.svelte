<script lang="ts">
  import { base } from '$app/paths';
  import { onMount } from 'svelte';
  import { Settings2 } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminPageLinkAction from '$lib/components/page/AdminPageLinkAction.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import KnowledgeAskPanel from './ask/KnowledgeAskPanel.svelte';
  import KnowledgeBrowsePanel from './browse/KnowledgeBrowsePanel.svelte';
  import KnowledgeIngestPanel from './ingest/KnowledgeIngestPanel.svelte';
  import {
    KNOWLEDGE_PREFERENCES_SECTION_HREF,
    KNOWLEDGE_TABS,
    type KnowledgeTabId
  } from './shared/knowledge-pure';
  import { createKnowledgePageController } from './state/knowledge-controller.svelte';

  /** Thin composition root: delegates orchestration to `state/knowledge-controller.svelte.ts`. */
  const ctl = createKnowledgePageController();
  onMount(ctl.mount);

  const tabDescriptors: readonly AdminTabDescriptor<KnowledgeTabId>[] = KNOWLEDGE_TABS.map(
    (tab) => ({ id: tab.id, label: tab.label, kind: 'pane' as const })
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
      active={ctl.activeTab}
      onSelect={(id) => {
        void ctl.setActiveTab(id);
      }}
    />
  {/snippet}

  {#snippet actions()}
    <AdminPageLinkAction
      href={`${base}${KNOWLEDGE_PREFERENCES_SECTION_HREF}`}
      icon={Settings2}
      title="Open workspace knowledge preferences"
    >
      Preferences
    </AdminPageLinkAction>
  {/snippet}

  {#if ctl.error}
    <InlineDestructiveAlert message={ctl.error} />
  {/if}

  {#if ctl.activeTab === 'ingest'}
    <KnowledgeIngestPanel {ctl} />
  {:else if ctl.activeTab === 'browse'}
    <KnowledgeBrowsePanel {ctl} />
  {:else}
    <KnowledgeAskPanel {ctl} />
  {/if}
</AdminPageHeader>
