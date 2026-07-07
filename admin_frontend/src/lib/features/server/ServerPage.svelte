<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
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

  // The Metrics subtab is gated by the `metrics` feature (features.ts). When hidden its tab is
  // dropped here and from the allowed-tab whitelist (server-preferences), so `?tab=metrics` falls
  // back to the default (Workspaces) tab.
  const tabDescriptors: readonly AdminTabDescriptor<ServerTabPreference>[] = [
    { id: 'workspaces', label: 'Workspaces', kind: 'pane' },
    { id: 'gateways', label: 'Gateways', kind: 'pane' },
    ...(isFeatureActive('metrics')
      ? [{ id: 'metrics', label: 'Metrics', kind: 'pane' } as AdminTabDescriptor<ServerTabPreference>]
      : [])
  ];

  onMount(() => {
    prefs.initialize();
  });
</script>

<AdminPageHeader kicker="Server operations" title="Server" sticky>
  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel="Server sections"
      tabs={tabDescriptors}
      active={prefs.activeTab}
      onSelect={(id) => prefs.setActiveTab(id)}
    />
  {/snippet}

  {#if prefs.activeTab === 'gateways'}
    <GatewaysTab notify={toasts.notify} />
  {:else if prefs.activeTab === 'metrics' && isFeatureActive('metrics')}
    <MetricsTab notify={toasts.notify} />
  {:else}
    <WorkspacesTab notify={toasts.notify} />
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
