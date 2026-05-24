<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import type { ChannelsDevicesTabPreference } from '$lib/preferences/keys';
  import { createChannelsDevicesPreferences } from '$lib/preferences/channels-devices-preferences.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import ChannelsTab from './ChannelsTab.svelte';
  import DevicesTab from './DevicesTab.svelte';

  const prefs = createChannelsDevicesPreferences();

  const toasts = createToastNotifier();

  const tabDescriptors: readonly AdminTabDescriptor<ChannelsDevicesTabPreference>[] = [
    { id: 'channels', label: 'Channels', kind: 'pane' },
    { id: 'devices', label: 'Devices', kind: 'pane' }
  ];

  onMount(() => {
    prefs.initialize();
  });
</script>

<AdminPageHeader kicker="Operations" title="Channels & Devices" sticky>
  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel="Channels and devices sections"
      tabs={tabDescriptors}
      active={prefs.activeTab}
      onSelect={(id) => prefs.setActiveTab(id)}
    />
  {/snippet}

  {#if prefs.activeTab === 'channels'}
    <ChannelsTab notify={toasts.notify} />
  {:else}
    <DevicesTab notify={toasts.notify} />
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
