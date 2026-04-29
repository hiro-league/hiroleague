<script lang="ts">
  import { onMount } from 'svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { createServerPreferences } from '$lib/preferences/server-preferences.svelte';
  import { cn } from '$lib/utils';
  import GatewaysTab from './GatewaysTab.svelte';
  import WorkspacesTab from './WorkspacesTab.svelte';
  import type { NotifyKind } from './types';

  const prefs = createServerPreferences();
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
      <p class="font-sans text-xs font-extrabold uppercase text-primary">Server operations</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Server</h2>
    </div>
    <div class="inline-flex rounded-lg border bg-card p-1" role="tablist" aria-label="Server sections">
      <Button
        class={cn(
          'shadow-none',
          prefs.activeTab === 'workspaces' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
        )}
        variant={prefs.activeTab === 'workspaces' ? 'secondary' : 'ghost'}
        role="tab"
        onclick={() => prefs.setActiveTab('workspaces')}
      >
        Workspaces
      </Button>
      <Button
        class={cn(
          'shadow-none',
          prefs.activeTab === 'gateways' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
        )}
        variant={prefs.activeTab === 'gateways' ? 'secondary' : 'ghost'}
        role="tab"
        onclick={() => prefs.setActiveTab('gateways')}
      >
        Gateways
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

  {#if prefs.activeTab === 'workspaces'}
    <WorkspacesTab {notify} />
  {:else}
    <GatewaysTab {notify} />
  {/if}
</section>
