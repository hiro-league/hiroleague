<script lang="ts">
  import { onMount } from 'svelte';
  import {
    BookOpen,
    Check,
    CircleHelp,
    Copy,
    CornerUpLeft,
    ExternalLink,
    FileWarning,
    FolderOpen,
    KeyRound,
    Play,
    RefreshCw,
    RotateCw,
    Settings,
    Square,
    Star,
    Trash2
  } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { DEFAULT_ADMIN_CONFIG, docsUrl, getAdminConfig, type AdminConfig } from '$lib/api/config';
  import { liveStatus } from '$lib/live/status.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import { createWorkspaceStore } from './workspace-store.svelte';
  import type { Notify } from './types';
  import type { WorkspaceRow } from '$lib/api/server';

  let { notify }: { notify: Notify } = $props();

  const WORKSPACE_GATEWAY_DOCS_PATH = '/hiro/cli/server-operations';

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

  function gatewayHttpUrl(url: string | null) {
    if (!url) return null;
    return url.replace(/^wss:/i, 'https:').replace(/^ws:/i, 'http:');
  }

  function statusUrl(row: WorkspaceRow) {
    return `http://127.0.0.1:${row.http_port}/status`;
  }

  function adminUrl(row: WorkspaceRow) {
    return `http://127.0.0.1:${row.admin_port}/`;
  }

  function formatStderrTime(value: string | null) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    });
  }

  function formatBytes(value: number) {
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  function stderrTitle(row: WorkspaceRow) {
    const updated = formatStderrTime(row.stderr_log_mtime);
    return `stderr.log${updated ? ` updated ${updated}` : ''} (${formatBytes(row.stderr_log_size)})`;
  }
  const WORKSPACE_GRID = '220px 110px 125px 1.25fr 105px 445px';
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
          <div
            class="{ADMIN_TABLE_GRID_ROW} items-center"
            style:grid-template-columns={WORKSPACE_GRID}
          >
            <span class="min-w-0">
              <span class="flex min-w-0 items-center gap-1.5">
                {#if row.is_default}
                  <Star
                    class="shrink-0 text-amber-500"
                    fill="currentColor"
                    size={15}
                    title={`Default workspace: ${row.name}`}
                  />
                {/if}
                <strong class="block truncate font-sans text-sm">{row.name}</strong>
                <button
                  class="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                  type="button"
                  onclick={() => workspace.openFolder(row)}
                  title={`Open workspace folder: ${row.path}`}
                  aria-label={`Open workspace folder: ${row.path}`}
                >
                  <FolderOpen size={13} />
                </button>
              </span>
            </span>
            <span class="self-center">
              <Badge variant={row.is_configured ? 'success' : 'warning'}>
                {row.is_configured ? 'Configured' : 'Needs setup'}
              </Badge>
            </span>
            <span class="space-y-1 self-center">
              <span class="flex items-center gap-1.5">
                {#if row.running}
                  <a href={statusUrl(row)} target="_blank" rel="noreferrer" title={statusUrl(row)}>
                    <Badge variant="success">Running</Badge>
                  </a>
                {:else}
                  <Badge variant="outline">Stopped</Badge>
                {/if}
                {#if row.is_current}
                  <CornerUpLeft
                    class="text-primary"
                    size={15}
                    title="Workspace of this Control Room"
                    aria-label="Workspace of this Control Room"
                  />
                {/if}
              </span>
              {#if row.pid && row.running}
                <small class="block text-xs text-muted-foreground">PID {row.pid}</small>
              {/if}
            </span>
            <span class="min-w-0 space-y-1 self-center text-xs text-muted-foreground">
              <span class="flex min-w-0 items-center gap-1.5">
                {#if row.gateway_url}
                  {#if row.running}
                    <a
                      class="truncate font-mono text-primary hover:underline"
                      href={gatewayHttpUrl(row.gateway_url) ?? undefined}
                      target="_blank"
                      rel="noreferrer"
                      title={row.gateway_url}
                    >
                      {row.gateway_url}
                    </a>
                  {:else}
                    <span class="truncate font-mono opacity-70" title={row.gateway_url}>{row.gateway_url}</span>
                  {/if}
                {:else}
                  <span>-</span>
                {/if}
              </span>
              <span class="flex flex-wrap items-center gap-2 font-sans">
                {#if row.running}
                  {#if !row.is_current}
                    <a class="inline-flex items-center gap-1 text-primary hover:underline" href={adminUrl(row)} target="_blank" rel="noreferrer" title={`Admin UI: ${adminUrl(row)}`}>
                      <ExternalLink size={12} /> admin
                    </a>
                  {/if}
                {:else}
                  <span>HTTP {row.http_port}</span>
                  <span>Admin {row.admin_port}</span>
                {/if}
              </span>
            </span>
            <span class="self-center">
              <Badge variant={row.autostart_method && row.autostart_method !== 'skipped' ? 'secondary' : 'outline'}>
                {row.autostart_method ?? '-'}
              </Badge>
            </span>
            <span class="flex flex-wrap items-center gap-1.5 self-center">
              {#if !row.is_configured}
                <Button size="sm" variant="outline" onclick={() => workspace.openSetup(row)}><Settings size={13} /> Setup</Button>
              {:else}
                <Button size="sm" variant="outline" onclick={() => workspace.openPublicKey(row)}><KeyRound size={13} /> Key</Button>
              {/if}
              {#if row.is_configured && !row.running}
                <Button size="sm" variant="outline" disabled={workspace.busy} onclick={() => workspace.start(row)}><Play size={13} /> Start</Button>
              {/if}
              {#if row.running && !row.is_current}
                <Button size="sm" variant="outline" disabled={workspace.busy} onclick={() => workspace.stop(row)}><Square size={13} /> Stop</Button>
              {/if}
              {#if row.running}
                <Button size="sm" variant="outline" onclick={() => workspace.openRestart(row)}><RotateCw size={13} /> Restart</Button>
              {/if}
              <Button size="sm" variant="outline" onclick={() => workspace.openEdit(row)}>Edit</Button>
              {#if row.stderr_log_exists}
                <Button
                  size="sm"
                  variant="outline"
                  class={row.stderr_log_recent ? 'border-destructive/50 text-destructive hover:bg-destructive/10 hover:text-destructive' : ''}
                  title={stderrTitle(row)}
                  onclick={() => workspace.openStderrLog(row)}
                >
                  <FileWarning size={13} /> stderr
                </Button>
              {/if}
              {#if !row.is_current}
                <Button size="sm" variant="destructive" onclick={() => workspace.openRemove(row)}><Trash2 size={13} /> Remove</Button>
              {:else}
                <Button
                  size="sm"
                  variant="outline"
                  class="opacity-45"
                  disabled
                  title="Cannot remove the workspace running this Admin UI"
                >
                  <Trash2 size={13} /> Remove
                </Button>
              {/if}
            </span>
          </div>
        {/each}
      {/snippet}
    </AdminTableShell>
  {/if}
</section>

<Dialog.Root
  open={workspace.dialog === 'create'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Create workspace</Dialog.Title>
    </Dialog.Header>
    <div class="grid gap-4">
      <FormField label="Name">
        {#snippet children()}
          <input bind:value={workspace.createForm.name} placeholder="e.g. work" />
        {/snippet}
      </FormField>
      <FormField label="Path (optional)">
        {#snippet children()}
          <input bind:value={workspace.createForm.path} placeholder="Leave blank for default location" />
        {/snippet}
      </FormField>
    </div>
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button disabled={workspace.busy} onclick={workspace.submitCreate}>Create</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root
  open={workspace.dialog === 'edit'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Edit workspace '{workspace.selected?.name ?? ''}'</Dialog.Title>
    </Dialog.Header>
    <div class="grid gap-4">
      <FormField label="Display name">
        {#snippet children()}
          <input bind:value={workspace.editForm.name} />
        {/snippet}
      </FormField>
      <FormField label="Gateway WebSocket URL">
        {#snippet children()}
          <input bind:value={workspace.editForm.gatewayUrl} placeholder="ws://myhost:8765" />
        {/snippet}
      </FormField>
      <label class="flex items-center gap-2 font-sans text-sm">
        <input type="checkbox" bind:checked={workspace.editForm.setDefault} />
        Set as default workspace
      </label>
    </div>
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button disabled={workspace.busy} onclick={workspace.submitEdit}>Save</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root
  open={workspace.dialog === 'remove'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Remove workspace '{workspace.selected?.name ?? ''}'</Dialog.Title>
      {#if workspace.selected?.path}
        <Dialog.Description>{workspace.selected.path}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <label class="flex items-center gap-2 font-sans text-sm">
      <input type="checkbox" bind:checked={workspace.removeForm.purge} />
      Also delete workspace folder from disk
    </label>
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button variant="destructive" disabled={workspace.busy} onclick={workspace.submitRemove}>Remove</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root
  open={workspace.dialog === 'restart'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Restart workspace '{workspace.selected?.name ?? ''}'</Dialog.Title>
      {#if workspace.selected?.path}
        <Dialog.Description>{workspace.selected.path}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <label class="flex items-center gap-2 font-sans text-sm">
      <input
        type="checkbox"
        bind:checked={workspace.restartForm.admin}
        disabled={workspace.selected?.id === workspace.hostingWorkspaceId}
      />
      Also start Admin UI on the restarted process
    </label>
    {#if workspace.selected?.id === workspace.hostingWorkspaceId}
      <p class="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
        This workspace is running the current Admin UI. Keep admin restart enabled.
      </p>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button disabled={workspace.busy} onclick={workspace.submitRestart}>Restart</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root
  open={workspace.dialog === 'setup'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Setup workspace '{workspace.selected?.name ?? ''}'</Dialog.Title>
      {#if workspace.selected?.path}
        <Dialog.Description>{workspace.selected.path}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <div class="grid gap-4">
      <FormField label="Gateway WebSocket URL">
        {#snippet children()}
          <input bind:value={workspace.setupForm.gatewayUrl} placeholder="ws://myhost:8765" />
        {/snippet}
      </FormField>
      <details class="grid gap-3 rounded-md border bg-muted/40 p-3">
        <summary class="cursor-pointer font-sans font-semibold">Advanced options</summary>
        <FormField label="HTTP port override">
          {#snippet children()}
            <input
              bind:value={workspace.setupForm.httpPort}
              inputmode="numeric"
              placeholder={`Auto-assigned: ${workspace.selected?.http_port ?? ''}`}
            />
          {/snippet}
        </FormField>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={workspace.setupForm.skipAutostart} />
          Skip auto-start registration
          <CircleHelp size={14} title="By default, the server is registered to start automatically on login." />
        </label>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={workspace.setupForm.startServer} />
          Start server immediately after setup
          <CircleHelp size={14} title="Start this workspace as soon as setup saves the gateway URL and keys." />
        </label>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={workspace.setupForm.elevatedTask} />
          Request elevated Task Scheduler entry
          <CircleHelp
            size={14}
            title="Windows only. Triggers a UAC prompt on the server machine and registers the startup task with highest privileges."
          />
        </label>
      </details>
    </div>
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button disabled={workspace.busy} onclick={workspace.submitSetup}>Run setup</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root
  open={workspace.dialog === 'setup-key'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Workspace '{workspace.selected?.name ?? ''}' configured</Dialog.Title>
      <Dialog.Description>Save this public key before closing.</Dialog.Description>
    </Dialog.Header>
    <p class="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
      Save this key. It will not be shown again after setup. Paste it into the Desktop public key field when creating a gateway instance for this workspace.
    </p>
    <span class="font-sans text-sm font-medium text-muted-foreground">Workspace public key (Ed25519, base64)</span>
    <div class="flex gap-2">
      <input class="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 font-mono text-sm" readonly value={workspace.setupPublicKey} />
      <Button
        class="size-9"
        variant="outline"
        size="icon"
        onclick={() => workspace.copyText(workspace.setupPublicKey)}
        aria-label="Copy public key"
        title="Copy to clipboard"
      >
        {#if workspace.copiedText === workspace.setupPublicKey}
          <Check class="text-emerald-500" size={16} />
        {:else}
          <Copy size={16} />
        {/if}
      </Button>
    </div>
    <Dialog.Footer>
      <Button onclick={workspace.closeDialog}>I've saved the key</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root
  open={workspace.dialog === 'public-key'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Public key - '{workspace.selected?.name ?? ''}'</Dialog.Title>
      <Dialog.Description>Regenerating invalidates existing gateway trust.</Dialog.Description>
    </Dialog.Header>
    <p class="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
      This key must be registered in every gateway instance that trusts this workspace. Regenerating it invalidates all existing gateway trust relationships.
    </p>
    <span class="font-sans text-sm font-medium text-muted-foreground">Workspace public key (Ed25519, base64)</span>
    <div class="flex gap-2">
      <input class="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 font-mono text-sm" readonly value={workspace.publicKey} />
      <Button
        class="size-9"
        variant="outline"
        size="icon"
        onclick={() => workspace.copyText(workspace.publicKey)}
        aria-label="Copy public key"
        title="Copy to clipboard"
      >
        {#if workspace.copiedText === workspace.publicKey}
          <Check class="text-emerald-500" size={16} />
        {:else}
          <Copy size={16} />
        {/if}
      </Button>
    </div>
    <Dialog.Footer>
      <Button variant="destructive" disabled={workspace.busy} onclick={workspace.regenerateKey}>Regenerate key</Button>
      <Button variant="outline" onclick={workspace.closeDialog}>Close</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
