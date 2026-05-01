<script lang="ts">
  import { base } from '$app/paths';
  import { onMount } from 'svelte';
  import { ArrowRight, Cable, KeyRound, RefreshCw, Router, Server } from '@lucide/svelte';
  import AdminShell from '$lib/shell/AdminShell.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { listActiveProviders, type ActiveProviderRow } from '$lib/api/catalog';
  import { listGateways, listWorkspaces, type GatewayRow, type WorkspaceRow } from '$lib/api/server';

  let activeProviders = $state<ActiveProviderRow[]>([]);
  let workspaces = $state<WorkspaceRow[]>([]);
  let gateways = $state<GatewayRow[]>([]);
  let loadingDashboard = $state(true);
  let dashboardError = $state<string | null>(null);

  const activeProviderNames = $derived(
    activeProviders.map((provider) => provider.display_name || provider.provider_id).slice(0, 2)
  );
  const activeProviderOverflow = $derived(Math.max(activeProviders.length - activeProviderNames.length, 0));
  const runningWorkspaces = $derived(workspaces.filter((workspace) => workspace.running));
  const runningGateways = $derived(gateways.filter((gateway) => gateway.running));
  const runningWorkspaceName = $derived(runningWorkspaces[0]?.name ?? 'None');
  const runningGatewayName = $derived(runningGateways[0]?.name ?? 'None');
  const gatewayLink = $derived(findGatewayLink(workspaces, gateways));

  function isLocalHost(host: string) {
    return ['0.0.0.0', '127.0.0.1', 'localhost', '::1'].includes(host.toLowerCase());
  }

  function workspaceGatewayTarget(workspace: WorkspaceRow) {
    if (!workspace.gateway_url) return null;
    try {
      const url = new URL(workspace.gateway_url);
      return { host: url.hostname, port: Number(url.port) };
    } catch {
      return null;
    }
  }

  function gatewayMatchesWorkspace(gateway: GatewayRow, workspace: WorkspaceRow) {
    const target = workspaceGatewayTarget(workspace);
    if (!target || !target.port || gateway.port !== target.port) return false;
    return gateway.host === target.host || (isLocalHost(gateway.host) && isLocalHost(target.host));
  }

  function findGatewayLink(workspaceRows: WorkspaceRow[], gatewayRows: GatewayRow[]) {
    for (const workspace of workspaceRows.filter((row) => row.running)) {
      const gateway = gatewayRows.find((row) => row.running && gatewayMatchesWorkspace(row, workspace));
      if (gateway) {
        return { workspace: workspace.name, gateway: gateway.name };
      }
    }
    return null;
  }

  async function loadDashboard() {
    loadingDashboard = true;
    dashboardError = null;
    try {
      const [providerPayload, workspacePayload, gatewayPayload] = await Promise.all([
        listActiveProviders(),
        listWorkspaces(),
        listGateways()
      ]);
      activeProviders = providerPayload.data;
      workspaces = workspacePayload.data;
      gateways = gatewayPayload.data;
    } catch (error) {
      dashboardError = error instanceof Error ? error.message : 'Unable to load dashboard status.';
      activeProviders = [];
      workspaces = [];
      gateways = [];
    } finally {
      loadingDashboard = false;
    }
  }

  onMount(loadDashboard);
</script>

<AdminShell>
  <section class="grid max-w-6xl gap-5">
    <div class="grid gap-6 rounded-lg border bg-card p-6 shadow-sm lg:grid-cols-[minmax(0,1fr)_320px]">
      <div>
        <p class="font-sans text-xs font-extrabold uppercase text-primary">Control Room</p>
        <h2 class="accent-text-gradient mt-2 max-w-3xl text-3xl font-semibold leading-tight md:text-4xl">
          Hiro workspace status and operations.
        </h2>
        <p class="mt-4 max-w-2xl text-base leading-7 text-muted-foreground">
          Monitor configured providers, running workspaces, and gateway connectivity from the
          local admin server.
        </p>
      </div>
      <div class="self-end rounded-lg border border-primary/30 bg-primary/10 p-4">
        <span class="font-sans text-sm text-muted-foreground">Admin package</span>
        <strong class="mt-1 block [overflow-wrap:anywhere] font-sans font-semibold">
          hirocli.admin_svelte.static
        </strong>
      </div>
    </div>

    <div class="flex items-center justify-between gap-3">
      {#if dashboardError}
        <span class="rounded-full border border-destructive/30 bg-destructive/10 px-3 py-1 font-sans text-xs font-semibold text-destructive">
          {dashboardError}
        </span>
      {:else}
        <span class="rounded-full border bg-muted px-3 py-1 font-sans text-xs font-semibold text-muted-foreground">
          {loadingDashboard ? 'Loading dashboard status' : 'Live dashboard status'}
        </span>
      {/if}
      <Button variant="outline" size="sm" disabled={loadingDashboard} onclick={loadDashboard}>
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
          <ArrowRight class="mt-1 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" size={18} />
        </div>

        <div class="grid gap-3">
          <div class="flex items-end gap-2">
            <strong class="font-sans text-4xl font-semibold leading-none">{loadingDashboard ? '-' : activeProviders.length}</strong>
            <span class="pb-1 font-sans text-sm font-semibold text-muted-foreground">active</span>
          </div>
          <div class="flex flex-wrap gap-2">
            {#if loadingDashboard}
              <span class="rounded-full bg-muted px-3 py-1 font-sans text-xs font-bold">Loading</span>
            {:else if activeProviderNames.length}
              {#each activeProviderNames as name}
                <span class="max-w-full truncate rounded-full bg-secondary px-3 py-1 font-sans text-xs font-bold text-secondary-foreground">{name}</span>
              {/each}
              {#if activeProviderOverflow}
                <span class="rounded-full border border-border px-3 py-1 font-sans text-xs font-bold text-muted-foreground">+{activeProviderOverflow}</span>
              {/if}
            {:else}
              <span class="rounded-full border border-border px-3 py-1 font-sans text-xs font-bold text-muted-foreground">None</span>
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
            <span class="rounded-full bg-emerald-500/15 p-2.5 text-emerald-700 dark:text-emerald-300"><Server size={20} /></span>
            <div>
              <h3 class="font-sans text-base font-semibold">Workspaces</h3>
              <span class="font-sans text-xs font-semibold text-muted-foreground">Registered and connected</span>
            </div>
          </div>
          <ArrowRight class="mt-1 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-emerald-700 dark:group-hover:text-emerald-300" size={18} />
        </div>

        <div class="grid gap-3">
          <div class="flex flex-wrap gap-2">
            <span class="rounded-full border bg-muted px-3 py-1 font-sans text-xs font-bold text-muted-foreground">
              {workspaces.length} registered
            </span>
            <span class="rounded-full bg-emerald-500/15 px-3 py-1 font-sans text-xs font-bold text-emerald-700 dark:text-emerald-300">
              {runningWorkspaces.length} connected
            </span>
          </div>
          <div class="flex min-w-0 items-center gap-2">
            <span class="font-sans text-sm font-semibold text-muted-foreground">Running</span>
            <strong class="min-w-0 truncate rounded-full bg-brand/20 px-3 py-1 font-sans text-lg font-extrabold leading-tight text-brand">
              {loadingDashboard ? 'Loading' : runningWorkspaceName}
            </strong>
          </div>
          {#if gatewayLink}
            <span class="inline-flex max-w-full items-center gap-2 rounded-full bg-gradient-to-r from-emerald-500/20 via-brand/20 to-cyan-500/20 px-3 py-1 font-sans text-xs font-extrabold text-foreground">
              <span class="truncate">{gatewayLink.workspace}</span>
              <Cable size={13} />
              <span class="truncate">{gatewayLink.gateway}</span>
            </span>
          {:else if !loadingDashboard}
            <span class="inline-flex w-fit rounded-full border border-border px-3 py-1 font-sans text-xs font-bold text-muted-foreground">No gateway link</span>
          {/if}
        </div>
      </a>

      <a
        class="group grid min-h-36 gap-3 rounded-lg border bg-card p-4 shadow-sm transition-colors hover:border-cyan-500/50 hover:bg-cyan-500/5"
        href={`${base}/server/?tab=gateways`}
      >
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-center gap-3">
            <span class="rounded-full bg-cyan-500/15 p-2.5 text-cyan-700 dark:text-cyan-300"><Router size={20} /></span>
            <div>
              <h3 class="font-sans text-base font-semibold">Gateways</h3>
              <span class="font-sans text-xs font-semibold text-muted-foreground">Registered and running</span>
            </div>
          </div>
          <ArrowRight class="mt-1 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-cyan-700 dark:group-hover:text-cyan-300" size={18} />
        </div>

        <div class="grid gap-3">
          <div class="flex flex-wrap gap-2">
            <span class="rounded-full border bg-muted px-3 py-1 font-sans text-xs font-bold text-muted-foreground">
              {gateways.length} registered
            </span>
            <span class="rounded-full bg-cyan-500/15 px-3 py-1 font-sans text-xs font-bold text-cyan-700 dark:text-cyan-300">
              {runningGateways.length} running
            </span>
          </div>
          <div class="flex min-w-0 items-center gap-2">
            <span class="font-sans text-sm font-semibold text-muted-foreground">Running</span>
            <strong class="min-w-0 truncate rounded-full bg-primary/20 px-3 py-1 font-sans text-lg font-extrabold leading-tight text-primary">
              {loadingDashboard ? 'Loading' : runningGatewayName}
            </strong>
          </div>
        </div>
      </a>
    </section>
  </section>
</AdminShell>
