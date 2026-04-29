<script lang="ts">
  import { onMount } from 'svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { createChannelsDevicesPreferences } from '$lib/preferences/channels-devices-preferences.svelte';
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

  {#if toast}
    <div
      class={cn(
        'w-fit max-w-full rounded-md border px-3 py-2 font-sans text-sm font-semibold',
        toast.kind === 'success' && 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
        toast.kind === 'error' && 'border-destructive/30 bg-destructive/10 text-destructive',
        toast.kind === 'warning' && 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
        toast.kind === 'info' && 'border-primary/30 bg-primary/10 text-primary'
      )}
    >
      {toast.message}
    </div>
  {/if}

  {#if prefs.activeTab === 'channels'}
    <ChannelsTab {notify} />
  {:else}
    <DevicesTab {notify} />
  {/if}
</section>
