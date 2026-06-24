<script lang="ts">
  import { base } from '$app/paths';
  import { Cable, KeyRound, RefreshCw, Router, Server } from '@lucide/svelte';
  import StatTile from '$lib/components/page/StatTile.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { DashboardController } from '$lib/features/dashboard/state/dashboard-controller.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';

  type Props = {
    ctrl: DashboardController;
  };

  let { ctrl }: Props = $props();

  const providers = $derived(ctrl.activeProvidersStore);
</script>

<div class="grid gap-5">
  <div class="flex items-center justify-between gap-3">
    {#if ctrl.error}
      <InlineDestructiveAlert message={ctrl.error} class="flex-1 text-xs" />
    {:else}
      <span class="rounded-full border bg-muted px-3 py-1 font-sans text-xs font-semibold text-muted-foreground">
        {ctrl.loading ? 'Loading dashboard status' : 'Live dashboard status'}
      </span>
    {/if}
    <Button variant="outline" size="sm" disabled={ctrl.loading} onclick={() => void ctrl.load()}>
      <RefreshCw size={14} /> Refresh
    </Button>
  </div>

  <section class="grid gap-4 md:grid-cols-3">
    <StatTile
      href={`${base}/catalog/?tab=active-providers`}
      title="Active Providers"
      subtitle="Configured AI access"
      icon={KeyRound}
      accent="primary"
    >
      {#snippet children()}
        <div class="flex items-end gap-2">
          <strong class="font-sans text-4xl font-semibold leading-none">
            {ctrl.loading ? '-' : providers.rows.length}
          </strong>
          <span class="pb-1 font-sans text-sm font-semibold text-muted-foreground">active</span>
        </div>
        <div class="flex flex-wrap gap-2">
          {#if ctrl.loading || providers.loading}
            <span class="rounded-full bg-muted px-3 py-1 font-sans text-xs font-bold">Loading</span>
          {:else if ctrl.activeProviderNames.length}
            {#each ctrl.activeProviderNames as name}
              <span
                class="max-w-full truncate rounded-full bg-secondary px-3 py-1 font-sans text-xs font-bold text-secondary-foreground"
              >
                {name}
              </span>
            {/each}
            {#if ctrl.activeProviderOverflow}
              <span
                class="rounded-full border border-border px-3 py-1 font-sans text-xs font-bold text-muted-foreground"
              >
                +{ctrl.activeProviderOverflow}
              </span>
            {/if}
          {:else}
            <span class="rounded-full border border-border px-3 py-1 font-sans text-xs font-bold text-muted-foreground">
              None
            </span>
          {/if}
        </div>
      {/snippet}
    </StatTile>

    <StatTile
      href={`${base}/server/?tab=workspaces`}
      title="Workspaces"
      subtitle="Registered and connected"
      icon={Server}
      accent="emerald"
    >
      {#snippet children()}
        <div class="flex flex-wrap gap-2">
          <span class="rounded-full border bg-muted px-3 py-1 font-sans text-xs font-bold text-muted-foreground">
            {ctrl.workspaces.length} registered
          </span>
          <span
            class="rounded-full bg-emerald-500/15 px-3 py-1 font-sans text-xs font-bold text-emerald-700 dark:text-emerald-300"
          >
            {ctrl.runningWorkspaces.length} connected
          </span>
        </div>
        <div class="flex min-w-0 items-center gap-2">
          <span class="font-sans text-sm font-semibold text-muted-foreground">Running</span>
          <strong
            class="min-w-0 truncate rounded-full bg-brand/20 px-3 py-1 font-sans text-lg font-extrabold leading-tight text-brand"
          >
            {ctrl.loading ? 'Loading' : ctrl.runningWorkspaceName}
          </strong>
        </div>
        {#if ctrl.gatewayLink}
          <span
            class="inline-flex max-w-full items-center gap-2 rounded-full bg-gradient-to-r from-emerald-500/20 via-brand/20 to-cyan-500/20 px-3 py-1 font-sans text-xs font-extrabold text-foreground"
          >
            <span class="truncate">{ctrl.gatewayLink.workspace}</span>
            <Cable size={13} />
            <span class="truncate">{ctrl.gatewayLink.gateway}</span>
          </span>
        {:else if !ctrl.loading}
          <span
            class="inline-flex w-fit rounded-full border border-border px-3 py-1 font-sans text-xs font-bold text-muted-foreground"
          >
            No gateway link
          </span>
        {/if}
      {/snippet}
    </StatTile>

    <StatTile
      href={`${base}/server/?tab=gateways`}
      title="Gateways"
      subtitle="Registered and running"
      icon={Router}
      accent="cyan"
    >
      {#snippet children()}
        <div class="flex flex-wrap gap-2">
          <span class="rounded-full border bg-muted px-3 py-1 font-sans text-xs font-bold text-muted-foreground">
            {ctrl.gateways.length} registered
          </span>
          <span
            class="rounded-full bg-cyan-500/15 px-3 py-1 font-sans text-xs font-bold text-cyan-700 dark:text-cyan-300"
          >
            {ctrl.runningGateways.length} running
          </span>
        </div>
        <div class="flex min-w-0 items-center gap-2">
          <span class="font-sans text-sm font-semibold text-muted-foreground">Running</span>
          <strong
            class="min-w-0 truncate rounded-full bg-primary/20 px-3 py-1 font-sans text-lg font-extrabold leading-tight text-primary"
          >
            {ctrl.loading ? 'Loading' : ctrl.runningGatewayName}
          </strong>
        </div>
      {/snippet}
    </StatTile>
  </section>
</div>
