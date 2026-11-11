<script lang="ts">
  import ResourceView from '$kit/ui/resource-view.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import { onMount } from 'svelte';
  import { BookOpen, RefreshCw } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import { DEFAULT_ADMIN_CONFIG, docsUrl, getAdminConfig, type AdminConfig } from '$lib/api/config';
  import { liveStatus } from '$lib/live/status.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import type { Notify } from '$kit/ui/toast.svelte';
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
      adminConfig = payload ?? DEFAULT_ADMIN_CONFIG;
    })
    .catch(() => {
      adminConfig = DEFAULT_ADMIN_CONFIG;
    });

  const view = $derived({
    data: workspace.rows.length || !(workspace.loading || workspace.error) ? workspace.rows : null,
    error: workspace.error ?? '',
    loading: workspace.loading,
    reload: () => workspace.load()
  });
</script>

<Panel title="Workspaces" description={`${workspace.rows.length} registered / ${workspace.configuredCount} configured / ${workspace.runningCount} running`}>
  {#snippet actions()}
    <a
      class="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      href={workspaceGatewayDocsUrl}
      target="_blank"
      rel="noreferrer"
      title={`Workspace and gateway CLI docs: ${workspaceGatewayDocsUrl}`}
      aria-label="Workspace and gateway CLI docs"
    >
      <BookOpen size={15} />
    </a>
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
  {/snippet}
  <ResourceView
    resource={view}
    loadingLabel="Loading workspaces…"
    errorTitle="Could not load workspaces"
    empty={(d) => d.length === 0}
    emptyMessage="No workspaces configured yet."
    quiet
  >
    {#snippet children()}
      <TableShell layout="grid" minWidth={1180} gridColumns={WORKSPACE_GRID}>
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
      </TableShell>
    {/snippet}
  </ResourceView>
</Panel>

<WorkspaceCreateDialog {workspace} />
<WorkspaceEditDialog {workspace} />
<WorkspaceRemoveDialog {workspace} />
<WorkspaceRestartDialog {workspace} />
<WorkspaceSetupDialog {workspace} />
<WorkspaceSetupKeyDialog {workspace} />
<WorkspacePublicKeyDialog {workspace} />
