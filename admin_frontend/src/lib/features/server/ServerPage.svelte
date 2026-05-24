<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import { createServerPreferences } from '$lib/preferences/server-preferences.svelte';
  import type { ServerTabPreference } from '$lib/preferences/keys';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import GatewaysTab from './GatewaysTab.svelte';
  import WorkspacesTab from './WorkspacesTab.svelte';

  const prefs = createServerPreferences();
  const toasts = createToastNotifier();

  const tabDescriptors: readonly AdminTabDescriptor<ServerTabPreference>[] = [
    { id: 'workspaces', label: 'Workspaces', kind: 'pane' },
    { id: 'gateways', label: 'Gateways', kind: 'pane' }
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

  {#if prefs.activeTab === 'workspaces'}
    <WorkspacesTab notify={toasts.notify} />
  {:else}
    <GatewaysTab notify={toasts.notify} />
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
