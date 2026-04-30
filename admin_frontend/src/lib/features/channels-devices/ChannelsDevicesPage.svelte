<script lang="ts">
  import { onMount } from 'svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { createChannelsDevicesPreferences } from '$lib/preferences/channels-devices-preferences.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { cn } from '$lib/utils';
  import ChannelsTab from './ChannelsTab.svelte';
  import DevicesTab from './DevicesTab.svelte';
  import type { NotifyKind } from './types';

  const prefs = createChannelsDevicesPreferences();
  let toast = $state<{ kind: NotifyKind; message: string } | null>(null);

  function notify(kind: NotifyKind, message: string) {
    toast = { kind, message };
    window.setTimeout(() => {
      toast = null;
    }, 4500);
  }

  onMount(() => {
    prefs.initialize();
  });
</script>

<section class="grid max-w-[1420px] gap-5">
  <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div>
      <p class="font-sans text-xs font-extrabold uppercase text-primary">Operations</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Channels & Devices</h2>
    </div>
    <div
      class="inline-flex rounded-lg border bg-card p-1"
      role="tablist"
      aria-label="Channels and devices sections"
    >
      <Button
        class={cn(
          'shadow-none',
          prefs.activeTab === 'channels' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
        )}
        variant={prefs.activeTab === 'channels' ? 'secondary' : 'ghost'}
        role="tab"
        onclick={() => prefs.setActiveTab('channels')}
      >
        Channels
      </Button>
      <Button
        class={cn(
          'shadow-none',
          prefs.activeTab === 'devices' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
        )}
        variant={prefs.activeTab === 'devices' ? 'secondary' : 'ghost'}
        role="tab"
        onclick={() => prefs.setActiveTab('devices')}
      >
        Devices
      </Button>
    </div>
  </div>

  {#if prefs.activeTab === 'channels'}
    <ChannelsTab {notify} />
  {:else}
    <DevicesTab {notify} />
  {/if}
</section>

<ToastHost {toast} />
