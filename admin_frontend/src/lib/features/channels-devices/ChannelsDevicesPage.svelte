<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import type { ChannelsDevicesTabPreference } from '$lib/preferences/keys';
  import { createChannelsDevicesPreferences } from '$lib/preferences/channels-devices-preferences.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { createChannelsController } from './state/channels-controller.svelte';
  import { createDevicesController } from './state/devices-controller.svelte';
  import ChannelsTab from './view/ChannelsTab.svelte';
  import DevicesTab from './view/DevicesTab.svelte';

  const prefs = createChannelsDevicesPreferences();

  const toasts = createToastNotifier();
  const channelsCtrl = createChannelsController(toasts.notify);
  const devicesCtrl = createDevicesController(toasts.notify);

  const tabDescriptors: readonly AdminTabDescriptor<ChannelsDevicesTabPreference>[] = [
    { id: 'channels', label: 'Channels', kind: 'pane' },
    { id: 'devices', label: 'Devices', kind: 'pane' }
  ];

  onMount(() => {
    prefs.initialize();
  });

  // The page owns the controllers' load lifecycle: (re)fetch the active tab's
  // data whenever the active tab changes. Tabs stay pure views (no onMount fetch).
  $effect(() => {
    if (prefs.activeTab === 'channels') {
      void channelsCtrl.load();
    } else {
      void devicesCtrl.load();
    }
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
    <ChannelsTab ctrl={channelsCtrl} notify={toasts.notify} />
  {:else}
    <DevicesTab ctrl={devicesCtrl} />
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
