<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
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
    { id: 'providers', label: 'Catalog providers', kind: 'pane' },
    { id: 'models', label: 'Models', kind: 'pane' }
  ];

  onMount(() => {
    void ctrl.initialize();
  });
</script>

<AdminPageHeader sticky kicker="AI Models" title="Model Catalog">
  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel="Catalog sections"
      tabs={tabDescriptors}
      active={ctrl.activeTab}
      onSelect={(id) => void ctrl.switchTab(id)}
    />
  {/snippet}

  {#if ctrl.activeTab === 'providers'}
    <ProvidersTab {ctrl} />
  {:else}
    <AdminPageStickyToolbar>
      <ModelsFilterBar {ctrl} />
    </AdminPageStickyToolbar>
    <ModelsTab {ctrl} />
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
