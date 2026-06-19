<script lang="ts">
  import {
    CornerUpLeft,
    ExternalLink,
    FolderOpen,
    KeyRound,
    Play,
    RotateCw,
    Settings,
    Square,
    Star,
    Trash2
  } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import type { WorkspaceRow } from '$lib/api/server';
  import AutostartBadge from '../shared/AutostartBadge.svelte';
  import StderrLogButton from '../shared/StderrLogButton.svelte';
  import { adminUrl, gatewayHttpUrl, statusUrl } from '../shared/server-format';
  import type { createWorkspaceStore } from '../state/workspace-store.svelte';

  let {
    row,
    workspace,
    grid
  }: {
    row: WorkspaceRow;
    workspace: ReturnType<typeof createWorkspaceStore>;
    grid: string;
  } = $props();
</script>

<div class="{ADMIN_TABLE_GRID_ROW} items-center" style:grid-template-columns={grid}>
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
        <a href={statusUrl(row.http_port)} target="_blank" rel="noreferrer" title={statusUrl(row.http_port)}>
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
          <a class="inline-flex items-center gap-1 text-primary hover:underline" href={adminUrl(row.admin_port)} target="_blank" rel="noreferrer" title={`Admin UI: ${adminUrl(row.admin_port)}`}>
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
    <AutostartBadge method={row.autostart_method} />
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
    <StderrLogButton
      exists={row.stderr_log_exists}
      recent={row.stderr_log_recent}
      mtime={row.stderr_log_mtime}
      size={row.stderr_log_size}
      onclick={() => workspace.openStderrLog(row)}
    />
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
