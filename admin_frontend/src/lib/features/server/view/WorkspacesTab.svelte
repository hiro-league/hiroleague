<script lang="ts">
  import { onMount } from 'svelte';
  import { BookOpen, RefreshCw } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { DEFAULT_ADMIN_CONFIG, docsUrl, getAdminConfig, type AdminConfig } from '$lib/api/config';
  import { liveStatus } from '$lib/live/status.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import type { Notify } from '$lib/ui/toast-types';
  import { createWorkspaceStore } from '../state/workspace-store.svelte';
  import WorkspaceRow from './WorkspaceRow.svelte';
  import WorkspaceCreateDialog from '../dialogs/WorkspaceCreateDialog.svelte';
  import WorkspaceEditDialog from '../dialogs/WorkspaceEditDialog.svelte';
  import WorkspaceRemoveDialog from '../dialogs/WorkspaceRemoveDialog.svelte';
  import WorkspaceRestartDialog from '../dialogs/WorkspaceRestartDialog.svelte';
  import WorkspaceSetupDialog from '../dialogs/WorkspaceSetupDialog.svelte';
  import WorkspaceSetupKeyDialog from '../dialogs/WorkspaceSetupKeyDialog.svelte';
  import WorkspacePublicKeyDialog from '../dialogs/WorkspacePublicKeyDialog.svelte';

  let { notify }: { notify: Notify } = $props();

  const WORKSPACE_GATEWAY_DOCS_PATH = '/hiro/cli/server-operations';
  const WORKSPACE_GRID = '220px 110px 125px 1.25fr 105px 445px';

  let adminConfig = $state<AdminConfig>(DEFAULT_ADMIN_CONFIG);
  const workspaceGatewayDocsUrl = $derived(docsUrl(adminConfig, WORKSPACE_GATEWAY_DOCS_PATH));
  const workspace = createWorkspaceStore((kind, message) => notify(kind, message));

  onMount(() => {
    workspace.load();
    return liveStatus.subscribe((status) => {
      workspace.applyLiveRows(status.workspaces, status.hosting_workspace_id, status.workspaces_error);
    });
  });

  getAdminConfig()
    .then((payload) => {
      adminConfig = payload.data ?? DEFAULT_ADMIN_CONFIG;
    })
    .catch(() => {
      adminConfig = DEFAULT_ADMIN_CONFIG;
    });
</script>

<section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <div class="flex items-center gap-2">
        <h3 class="text-lg font-semibold">Workspaces</h3>
        <a
          class="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          href={workspaceGatewayDocsUrl}
          target="_blank"
          rel="noreferrer"
          title={`Workspace and gateway CLI docs: ${workspaceGatewayDocsUrl}`}
          aria-label="Workspace and gateway CLI docs"
        >
          <BookOpen size={15} />
        </a>
      </div>
      <span class="font-sans text-sm text-muted-foreground">
        {workspace.rows.length} registered / {workspace.configuredCount} configured / {workspace.runningCount} running
      </span>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button
        class="size-9 px-0"
        variant="outline"
        onclick={() => workspace.load()}
        aria-label="Refresh workspaces"
        title="Refresh workspaces"
      >
        <RefreshCw size={15} />
      </Button>
      <Button onclick={workspace.openCreate}>Create workspace</Button>
    </div>
  </div>

  {#if workspace.loading}
    <InlineLoading label="Loading workspaces…" />
  {:else if workspace.error}
    <InlineDestructiveAlert title="Could not load workspaces" message={workspace.error} />
  {:else if workspace.rows.length === 0}
    <InlineEmptyState message="No workspaces configured yet." />
  {:else}
    <AdminTableShell layout="grid" minWidth={1180} gridColumns={WORKSPACE_GRID}>
      {#snippet headRow()}
        <span>Name</span>
        <span>Setup</span>
        <span>Status</span>
        <span>Gateway</span>
        <span>Autostart</span>
        <span>Actions</span>
      {/snippet}
      {#snippet body()}
        {#each workspace.rows as row (row.id)}
          <WorkspaceRow {row} {workspace} grid={WORKSPACE_GRID} />
        {/each}
      {/snippet}
    </AdminTableShell>
  {/if}
</section>

<WorkspaceCreateDialog {workspace} />
<WorkspaceEditDialog {workspace} />
<WorkspaceRemoveDialog {workspace} />
<WorkspaceRestartDialog {workspace} />
<WorkspaceSetupDialog {workspace} />
<WorkspaceSetupKeyDialog {workspace} />
<WorkspacePublicKeyDialog {workspace} />
