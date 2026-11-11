<script lang="ts">
  import { onMount } from 'svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import PageTabs from '$kit/ui/page-tabs.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import type { ChannelsDevicesTabPreference } from '$lib/preferences/keys';
  import { createChannelsDevicesPreferences } from '$lib/preferences/channels-devices-preferences.svelte';
  import { toast } from '$kit/ui/toast.svelte';
  import { isFeatureActive } from '$lib/shell/features';
  import { createChannelsController } from './state/channels-controller.svelte';
  import { createDevicesController } from './state/devices-controller.svelte';
  import ChannelsTab from './view/ChannelsTab.svelte';
  import DevicesTab from './view/DevicesTab.svelte';

  const prefs = createChannelsDevicesPreferences();

  const channelsCtrl = createChannelsController(toast.show);
  const devicesCtrl = createDevicesController(toast.show);

  // The Devices tab is gated by the `devices` feature (features.ts). When hidden the tab is dropped
  // here and from the allowed-tab whitelist (channels-devices-preferences), so a hidden
  // `?tab=devices` falls back to the default (Channels) tab.
  const devicesActive = isFeatureActive('devices');
  const tabDescriptors: readonly AdminTabDescriptor<ChannelsDevicesTabPreference>[] = [
    { id: 'channels', label: 'Channels', kind: 'pane' },
    ...(devicesActive
      ? [{ id: 'devices', label: 'Devices', kind: 'pane' } as AdminTabDescriptor<ChannelsDevicesTabPreference>]
      : [])
  ];

  onMount(() => {
    prefs.initialize();
  });

  // The page owns the controllers' load lifecycle: (re)fetch the active tab's
  // data whenever the active tab changes. Tabs stay pure views (no onMount fetch).
  $effect(() => {
    if (prefs.activeTab === 'channels') {
      void channelsCtrl.load();
    } else if (devicesActive) {
      void devicesCtrl.load();
    }
  });
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Channels & Devices">
    {#snippet tabs()}
    <PageTabs
      label="Channels and devices sections"
      tabs={tabDescriptors}
      value={prefs.activeTab}
      onchange={(id) => prefs.setActiveTab(id)}
    />
    {/snippet}
  </PageHeader>
  

  {#if prefs.activeTab === 'channels'}
    <ChannelsTab ctrl={channelsCtrl} notify={toast.show} />
  {:else if devicesActive}
    <DevicesTab ctrl={devicesCtrl} />
  {/if}
</section>

