<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import ModelsFilterBar from '$lib/features/catalog/browse/ModelsFilterBar.svelte';
  import ModelsTab from '$lib/features/catalog/browse/ModelsTab.svelte';
  import ProvidersTab from '$lib/features/catalog/browse/ProvidersTab.svelte';
  import AiProfilesTab from '$lib/features/catalog/ai/AiProfilesTab.svelte';
  import AiUsesTab from '$lib/features/catalog/ai/AiUsesTab.svelte';
  import LocalServerDialog from '$lib/features/catalog/ai/LocalServerDialog.svelte';
  import LocalServerProviderRows from '$lib/features/catalog/ai/LocalServerProviderRows.svelte';
  import PlanProviderRows from '$lib/features/catalog/ai/PlanProviderRows.svelte';
  import PlanToolDialog from '$lib/features/catalog/ai/PlanToolDialog.svelte';
  import { createAiController } from '$lib/features/catalog/ai/ai-controller.svelte';
  import { LOCAL_SERVER_IDS } from '$lib/features/catalog/ai/ai-profile-rules';
  import { createCatalogController } from '$lib/features/catalog/state/catalog-controller.svelte';
  import type { CatalogTabPreference } from '$lib/preferences/keys';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';

  const toasts = createToastNotifier();
  const ctrl = createCatalogController(toasts.notify);
  // Phase 7a: AI profiles, uses, local servers and plan tools (`/api/ai`).
  const ai = createAiController(toasts.notify, ctrl);

  const tabDescriptors: readonly AdminTabDescriptor<CatalogTabPreference>[] = [
    // Providers tab merges the former Active + Catalog provider tabs into one list.
    { id: 'providers', label: 'Providers', kind: 'pane' },
    { id: 'models', label: 'Models', kind: 'pane' },
    { id: 'profiles', label: 'AI profiles', kind: 'pane' },
    { id: 'uses', label: 'Uses', kind: 'pane' }
  ];

  // Local servers (LM Studio, Ollama) and, once read, plan tools (Claude Code, Codex) draw their own
  // rows with live status; the table skips the catalog's rows for them.
  const replacedProviderIds = $derived(new Set<string>([...LOCAL_SERVER_IDS, ...ai.plans.map((t) => t.id)]));

  onMount(() => {
    void ctrl.initialize();
    void ai.initialize();
    return () => ai.dispose();
  });
</script>

<AdminPageHeader sticky kicker="Configuration" title="Providers/Models">
  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel="Providers and models sections"
      tabs={tabDescriptors}
      active={ctrl.activeTab}
      onSelect={(id) => void ctrl.switchTab(id)}
    />
  {/snippet}

  {#if ctrl.activeTab === 'models'}
    <AdminPageStickyToolbar>
      <ModelsFilterBar {ctrl} />
    </AdminPageStickyToolbar>
    <ModelsTab {ctrl} />
  {:else if ctrl.activeTab === 'profiles'}
    <AiProfilesTab {ai} />
  {:else if ctrl.activeTab === 'uses'}
    <AiUsesTab {ai} />
  {:else}
    <!-- Phase 7a: the local servers' rows and the plan tools' rows, with their dialogs. -->
    <ProvidersTab {ctrl} {replacedProviderIds}>
      {#snippet extraRows(activeOnly: boolean)}
        <LocalServerProviderRows {ai} catalogProviders={ctrl.providers} {activeOnly} />
        <PlanProviderRows {ai} {activeOnly} />
      {/snippet}
    </ProvidersTab>
    <LocalServerDialog {ai} />
    <PlanToolDialog {ai} />
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
