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
  import Modal from '$lib/ui/Modal.svelte';
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
    <p class="text-muted-foreground">Loading workspaces...</p>
  {:else if workspace.error}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
      <strong class="font-sans">Could not load workspaces</strong>
      <span class="block text-sm">{workspace.error}</span>
    </div>
  {:else if workspace.rows.length === 0}
    <p class="text-muted-foreground">No workspaces configured yet.</p>
  {:else}
    <div class="overflow-x-auto rounded-md border">
      <div class="min-w-[1180px]">
        <div class="grid grid-cols-[220px_110px_125px_1.25fr_105px_445px] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground">
          <span>Name</span>
          <span>Setup</span>
          <span>Status</span>
          <span>Gateway</span>
          <span>Autostart</span>
          <span>Actions</span>
        </div>
        {#each workspace.rows as row}
          <div class="grid min-h-16 grid-cols-[220px_110px_125px_1.25fr_105px_445px] items-center gap-3 border-t px-3 py-3">
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
      </div>
    </div>
  {/if}
</section>

<Modal open={workspace.dialog === 'create'} title="Create workspace" onClose={workspace.closeDialog}>
  <label>Name<input bind:value={workspace.createForm.name} placeholder="e.g. work" /></label>
  <label>Path <small>optional</small><input bind:value={workspace.createForm.path} placeholder="Leave blank for default location" /></label>
  {#snippet footer()}
    <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
    <Button disabled={workspace.busy} onclick={workspace.submitCreate}>Create</Button>
  {/snippet}
</Modal>

<Modal open={workspace.dialog === 'edit'} title={`Edit workspace '${workspace.selected?.name ?? ''}'`} onClose={workspace.closeDialog}>
  <label>Display name<input bind:value={workspace.editForm.name} /></label>
  <label>Gateway WebSocket URL<input bind:value={workspace.editForm.gatewayUrl} placeholder="ws://myhost:8765" /></label>
  <label class="check-row"><input type="checkbox" bind:checked={workspace.editForm.setDefault} /> Set as default workspace</label>
  {#snippet footer()}
    <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
    <Button disabled={workspace.busy} onclick={workspace.submitEdit}>Save</Button>
  {/snippet}
</Modal>

<Modal open={workspace.dialog === 'remove'} title={`Remove workspace '${workspace.selected?.name ?? ''}'`} subtitle={workspace.selected?.path ?? ''} onClose={workspace.closeDialog}>
  <label class="check-row"><input type="checkbox" bind:checked={workspace.removeForm.purge} /> Also delete workspace folder from disk</label>
  {#snippet footer()}
    <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
    <Button variant="destructive" disabled={workspace.busy} onclick={workspace.submitRemove}>Remove</Button>
  {/snippet}
</Modal>

<Modal open={workspace.dialog === 'restart'} title={`Restart workspace '${workspace.selected?.name ?? ''}'`} subtitle={workspace.selected?.path ?? ''} onClose={workspace.closeDialog}>
  <label class="check-row">
    <input type="checkbox" bind:checked={workspace.restartForm.admin} disabled={workspace.selected?.id === workspace.hostingWorkspaceId} />
    Also start Admin UI on the restarted process
  </label>
  {#if workspace.selected?.id === workspace.hostingWorkspaceId}
    <p class="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
      This workspace is running the current Admin UI. Keep admin restart enabled.
    </p>
  {/if}
  {#snippet footer()}
    <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
    <Button disabled={workspace.busy} onclick={workspace.submitRestart}>Restart</Button>
  {/snippet}
</Modal>

<Modal open={workspace.dialog === 'setup'} title={`Setup workspace '${workspace.selected?.name ?? ''}'`} subtitle={workspace.selected?.path ?? ''} onClose={workspace.closeDialog}>
  <label>Gateway WebSocket URL<input bind:value={workspace.setupForm.gatewayUrl} placeholder="ws://myhost:8765" /></label>
  <details>
    <summary>Advanced options</summary>
    <label>HTTP port override<input bind:value={workspace.setupForm.httpPort} inputmode="numeric" placeholder={`Auto-assigned: ${workspace.selected?.http_port ?? ''}`} /></label>
    <label class="check-row">
      <input type="checkbox" bind:checked={workspace.setupForm.skipAutostart} />
      Skip auto-start registration
      <CircleHelp size={14} title="By default, the server is registered to start automatically on login." />
    </label>
    <label class="check-row">
      <input type="checkbox" bind:checked={workspace.setupForm.startServer} />
      Start server immediately after setup
      <CircleHelp size={14} title="Start this workspace as soon as setup saves the gateway URL and keys." />
    </label>
    <label class="check-row">
      <input type="checkbox" bind:checked={workspace.setupForm.elevatedTask} />
      Request elevated Task Scheduler entry
      <CircleHelp size={14} title="Windows only. Triggers a UAC prompt on the server machine and registers the startup task with highest privileges." />
    </label>
  </details>
  {#snippet footer()}
    <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
    <Button disabled={workspace.busy} onclick={workspace.submitSetup}>Run setup</Button>
  {/snippet}
</Modal>

<Modal open={workspace.dialog === 'setup-key'} title={`Workspace '${workspace.selected?.name ?? ''}' configured`} subtitle="Save this public key before closing." onClose={workspace.closeDialog}>
  <p class="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
    Save this key. It will not be shown again after setup. Paste it into the Desktop public key field when creating a gateway instance for this workspace.
  </p>
  <span class="font-sans text-sm font-medium text-muted-foreground">Workspace public key (Ed25519, base64)</span>
  <div class="flex gap-2">
    <input class="min-w-0 flex-1 font-mono" readonly value={workspace.setupPublicKey} />
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
  {#snippet footer()}
    <Button onclick={workspace.closeDialog}>I've saved the key</Button>
  {/snippet}
</Modal>

<Modal open={workspace.dialog === 'public-key'} title={`Public key - '${workspace.selected?.name ?? ''}'`} subtitle="Regenerating invalidates existing gateway trust." onClose={workspace.closeDialog}>
  <p class="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
    This key must be registered in every gateway instance that trusts this workspace. Regenerating it invalidates all existing gateway trust relationships.
  </p>
  <span class="font-sans text-sm font-medium text-muted-foreground">Workspace public key (Ed25519, base64)</span>
  <div class="flex gap-2">
    <input class="min-w-0 flex-1 font-mono" readonly value={workspace.publicKey} />
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
  {#snippet footer()}
    <Button variant="destructive" disabled={workspace.busy} onclick={workspace.regenerateKey}>Regenerate key</Button>
    <Button variant="outline" onclick={workspace.closeDialog}>Close</Button>
  {/snippet}
</Modal>
