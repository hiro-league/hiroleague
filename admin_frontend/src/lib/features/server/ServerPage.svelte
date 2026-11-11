<script lang="ts">
  import { onMount } from 'svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import PageTabs from '$kit/ui/page-tabs.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import { createServerPreferences } from '$lib/preferences/server-preferences.svelte';
  import type { ServerTabPreference } from '$lib/preferences/keys';
  import { isFeatureActive } from '$lib/shell/features';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import MetricsTab from '$lib/features/metrics/MetricsTab.svelte';
  import GatewaysTab from './view/GatewaysTab.svelte';
  import WorkspacesTab from './view/WorkspacesTab.svelte';

  const prefs = createServerPreferences();
  const toasts = createToastNotifier();

  // The Gateways and Metrics subtabs are each gated by their feature (features.ts). When hidden a
  // tab is dropped here and from the allowed-tab whitelist (server-preferences), so a hidden
  // `?tab=gateways`/`?tab=metrics` falls back to the default (Workspaces) tab.
  const tabDescriptors: readonly AdminTabDescriptor<ServerTabPreference>[] = [
    { id: 'workspaces', label: 'Workspaces', kind: 'pane' },
    ...(isFeatureActive('gateway')
      ? [{ id: 'gateways', label: 'Gateways', kind: 'pane' } as AdminTabDescriptor<ServerTabPreference>]
      : []),
    ...(isFeatureActive('metrics')
      ? [{ id: 'metrics', label: 'Metrics', kind: 'pane' } as AdminTabDescriptor<ServerTabPreference>]
      : [])
  ];

  onMount(() => {
    prefs.initialize();
  });
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Server">
    {#snippet tabs()}
    <PageTabs
      label="Server sections"
      tabs={tabDescriptors}
      value={prefs.activeTab}
      onchange={(id) => prefs.setActiveTab(id)}
    />
    {/snippet}
  </PageHeader>
  

  {#if prefs.activeTab === 'gateways' && isFeatureActive('gateway')}
    <GatewaysTab notify={toasts.notify} />
  {:else if prefs.activeTab === 'metrics' && isFeatureActive('metrics')}
    <MetricsTab notify={toasts.notify} />
  {:else}
    <WorkspacesTab notify={toasts.notify} />
  {/if}
</section>

<ToastHost toast={toasts.toast} />
