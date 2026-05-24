<script lang="ts">
  import { base } from '$app/paths';
  import { ArrowRight, Cable, KeyRound, RefreshCw, Router, Server } from '@lucide/svelte';
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
    <a
      class="group grid min-h-36 gap-3 rounded-lg border bg-card p-4 shadow-sm transition-colors hover:border-primary/50 hover:bg-secondary/20"
      href={`${base}/active-providers/`}
    >
      <div class="flex items-start justify-between gap-3">
        <div class="flex items-center gap-3">
          <span class="rounded-full bg-primary/15 p-2.5 text-primary"><KeyRound size={20} /></span>
          <div>
            <h3 class="font-sans text-base font-semibold">Active Providers</h3>
            <span class="font-sans text-xs font-semibold text-muted-foreground">Configured AI access</span>
          </div>
        </div>
        <ArrowRight
          class="mt-1 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary"
          size={18}
        />
      </div>

      <div class="grid gap-3">
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
      </div>
    </a>

    <a
      class="group grid min-h-36 gap-3 rounded-lg border bg-card p-4 shadow-sm transition-colors hover:border-emerald-500/50 hover:bg-emerald-500/5"
      href={`${base}/server/?tab=workspaces`}
    >
      <div class="flex items-start justify-between gap-3">
        <div class="flex items-center gap-3">
          <span class="rounded-full bg-emerald-500/15 p-2.5 text-emerald-700 dark:text-emerald-300">
            <Server size={20} />
          </span>
          <div>
            <h3 class="font-sans text-base font-semibold">Workspaces</h3>
            <span class="font-sans text-xs font-semibold text-muted-foreground">Registered and connected</span>
          </div>
        </div>
        <ArrowRight
          class="mt-1 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-emerald-700 dark:group-hover:text-emerald-300"
          size={18}
        />
      </div>

      <div class="grid gap-3">
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
      </div>
    </a>

    <a
      class="group grid min-h-36 gap-3 rounded-lg border bg-card p-4 shadow-sm transition-colors hover:border-cyan-500/50 hover:bg-cyan-500/5"
      href={`${base}/server/?tab=gateways`}
    >
      <div class="flex items-start justify-between gap-3">
        <div class="flex items-center gap-3">
          <span class="rounded-full bg-cyan-500/15 p-2.5 text-cyan-700 dark:text-cyan-300">
            <Router size={20} />
          </span>
          <div>
            <h3 class="font-sans text-base font-semibold">Gateways</h3>
            <span class="font-sans text-xs font-semibold text-muted-foreground">Registered and running</span>
          </div>
        </div>
        <ArrowRight
          class="mt-1 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-cyan-700 dark:group-hover:text-cyan-300"
          size={18}
        />
      </div>

      <div class="grid gap-3">
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
      </div>
    </a>
  </section>
</div>
