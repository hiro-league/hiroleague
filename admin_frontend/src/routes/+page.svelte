<script lang="ts">
  import { RefreshCw } from '@lucide/svelte';
  import AdminShell from '$lib/shell/AdminShell.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';

  type WorkspaceRow = {
    id: string;
    name: string;
    path: string;
    running: boolean;
    pid: number | null;
    is_current: boolean;
    is_default?: boolean;
    is_configured?: boolean;
    admin_port?: number;
    http_port?: number;
  };

  type WorkspaceResponse = {
    ok: boolean;
    error: string | null;
    data: WorkspaceRow[];
    hosting_workspace_id?: string | null;
  };

  const activity = [
    { time: '09:42', title: 'Workspace loaded', detail: 'local-dev resolved from runtime context' },
    { time: '09:47', title: 'Log stream idle', detail: 'API contract will replace NiceGUI polling' },
    { time: '09:53', title: 'Character editor planned', detail: 'Next migration candidate after logs' }
  ];

  let workspaces = $state<WorkspaceRow[]>([]);
  let workspaceError = $state<string | null>(null);
  let loadingWorkspaces = $state(true);

  const runningCount = $derived(workspaces.filter((workspace) => workspace.running).length);
  const configuredCount = $derived(workspaces.filter((workspace) => workspace.is_configured).length);
  const currentWorkspace = $derived(
    workspaces.find((workspace) => workspace.is_current)?.name ?? 'Not resolved'
  );
  const stats = $derived([
    { label: 'Registered workspaces', value: String(workspaces.length), trend: `${runningCount} running` },
    { label: 'Configured workspaces', value: String(configuredCount), trend: 'from WorkspaceService' },
    { label: 'Hosting workspace', value: currentWorkspace, trend: 'served by Hiro admin API' }
  ]);

  async function loadWorkspaces() {
    loadingWorkspaces = true;
    workspaceError = null;
    try {
      const response = await fetch('/admin-next/api/workspaces');
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = (await response.json()) as WorkspaceResponse;
      if (!payload.ok) {
        throw new Error(payload.error ?? 'Workspace API returned an error.');
      }
      workspaces = payload.data;
    } catch (error) {
      workspaceError =
        error instanceof Error
          ? error.message
          : 'Unable to load workspaces from the Hiro admin API.';
      workspaces = [];
    } finally {
      loadingWorkspaces = false;
    }
  }

  loadWorkspaces();
</script>

<AdminShell>
  <section class="grid max-w-6xl gap-5">
    <div class="grid gap-6 rounded-lg border bg-card p-6 shadow-sm lg:grid-cols-[minmax(0,1fr)_320px]">
      <div>
        <p class="font-sans text-xs font-extrabold uppercase text-primary">SvelteKit migration proof</p>
        <h2 class="accent-text-gradient mt-2 max-w-3xl text-3xl font-semibold leading-tight md:text-4xl">
          Same Hiro backend, cleaner browser-owned UI state.
        </h2>
        <p class="mt-4 max-w-2xl text-base leading-7 text-muted-foreground">
          This POC keeps NiceGUI untouched while proving the future admin shell, static build,
          and Python package integration path.
        </p>
      </div>
      <div class="self-end rounded-lg border border-primary/30 bg-primary/10 p-4">
        <span class="font-sans text-sm text-muted-foreground">Build target</span>
        <strong class="mt-1 block [overflow-wrap:anywhere] font-sans font-semibold">
          hirocli.admin_svelte.static
        </strong>
      </div>
    </div>

    <div class="grid gap-4 md:grid-cols-3">
      {#each stats as stat}
        <article class="rounded-lg border bg-card p-5 shadow-sm">
          <span class="font-sans text-sm text-muted-foreground">{stat.label}</span>
          <strong class="mt-2 block font-sans text-3xl font-semibold">{stat.value}</strong>
          <small class="mt-1 block font-sans text-sm text-muted-foreground">{stat.trend}</small>
        </article>
      {/each}
    </div>

    <section class="grid gap-4 lg:grid-cols-2">
      <article class="rounded-lg border bg-card p-5 shadow-sm">
        <div class="mb-4 flex items-center justify-between gap-3">
          <h3 class="text-base font-semibold">Workspaces</h3>
          <Button variant="outline" size="sm" onclick={loadWorkspaces}>
            <RefreshCw size={14} /> Refresh
          </Button>
        </div>
        {#if loadingWorkspaces}
          <p class="text-muted-foreground">Loading from /admin-next/api/workspaces...</p>
        {:else if workspaceError}
          <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
            <strong class="font-sans">Could not load workspaces</strong>
            <span class="block text-sm">{workspaceError}</span>
          </div>
        {:else}
          <div class="overflow-hidden rounded-md border">
            <div class="grid grid-cols-[minmax(0,1.4fr)_120px_120px] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground">
              <span>Name</span>
              <span>Status</span>
              <span>Ports</span>
            </div>
            {#each workspaces as workspace}
              <div class="grid min-h-14 grid-cols-[minmax(0,1.4fr)_120px_120px] gap-3 border-t px-3 py-2">
                <span class="min-w-0">
                  <strong class="block truncate font-sans text-sm">{workspace.name}</strong>
                  <small class="block truncate text-xs text-muted-foreground">{workspace.id}</small>
                </span>
                <span class="space-y-1">
                  <Badge variant={workspace.running ? 'success' : 'outline'}>
                    {workspace.running ? 'Running' : 'Stopped'}
                  </Badge>
                  {#if workspace.is_current}
                    <small class="block font-sans text-xs font-semibold text-primary">this UI</small>
                  {/if}
                </span>
                <span class="text-xs text-muted-foreground">
                  <small class="block">HTTP {workspace.http_port ?? '-'}</small>
                  <small class="block">Admin {workspace.admin_port ?? '-'}</small>
                </span>
              </div>
            {/each}
          </div>
        {/if}
      </article>

      <article class="rounded-lg border bg-card p-5 shadow-sm">
        <div class="mb-4 flex items-center justify-between gap-3">
          <h3 class="text-base font-semibold">Recent Activity</h3>
          <Badge variant="outline">Dummy data</Badge>
        </div>
        <div class="grid gap-2">
          {#each activity as item}
            <div class="grid grid-cols-[52px_minmax(0,1fr)] gap-3 rounded-md border bg-muted/40 p-3">
              <time class="font-sans text-sm font-bold text-brand">{item.time}</time>
              <div class="min-w-0">
                <strong class="font-sans text-sm">{item.title}</strong>
                <p class="mt-1 text-sm text-muted-foreground">{item.detail}</p>
              </div>
            </div>
          {/each}
        </div>
      </article>
    </section>
  </section>
</AdminShell>
