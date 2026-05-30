<script lang="ts">
  import { onMount } from 'svelte';
  import { RefreshCw } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import { cn } from '$lib/utils';
  import ActiveProvidersPanel from '$lib/catalog/active-providers/ActiveProvidersPanel.svelte';
  import ModelsFilterBar from '$lib/features/catalog/browse/ModelsFilterBar.svelte';
  import ModelsTab from '$lib/features/catalog/browse/ModelsTab.svelte';
  import ProvidersTab from '$lib/features/catalog/browse/ProvidersTab.svelte';
  import { createCatalogController } from '$lib/features/catalog/state/catalog-controller.svelte';
  import type { CatalogTabPreference } from '$lib/preferences/keys';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';

  const toasts = createToastNotifier();
  const ctrl = createCatalogController(toasts.notify);

  const tabDescriptors: readonly AdminTabDescriptor<CatalogTabPreference>[] = [
    { id: 'active-providers', label: 'Active providers', kind: 'pane' },
    { id: 'providers', label: 'Catalog providers', kind: 'pane' },
    { id: 'models', label: 'Models', kind: 'pane' }
  ];

  onMount(() => {
    void ctrl.initialize();
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

  {#snippet actions()}
    <Button
      variant="outline"
      disabled={ctrl.catalogReloadBusy}
      title="Re-read bundled catalog.yaml from disk on the server, clear the in-memory cache, then refresh lists"
      onclick={() => void ctrl.reloadBundledCatalog()}
    >
      <RefreshCw size={15} class={cn(ctrl.catalogReloadBusy && 'animate-spin')} />
      Reload catalog
    </Button>
  {/snippet}

  {#if ctrl.activeTab === 'active-providers'}
    <ActiveProvidersPanel
      store={ctrl.activeProvidersStore}
      notify={toasts.notify}
      catalogProviders={ctrl.providers}
      onOpenModelsForProvider={(providerId) => void ctrl.openModelsForProvider(providerId)}
    />
  {:else if ctrl.activeTab === 'providers'}
    <ProvidersTab {ctrl} />
  {:else}
    <AdminPageStickyToolbar>
      <ModelsFilterBar {ctrl} />
    </AdminPageStickyToolbar>
    <ModelsTab {ctrl} />
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
