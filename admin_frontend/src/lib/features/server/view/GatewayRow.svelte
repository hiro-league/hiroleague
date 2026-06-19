<script lang="ts">
  import { FolderOpen, Play, Square, Star, Trash2 } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import type { GatewayRow } from '$lib/api/server';
  import AutostartBadge from '../shared/AutostartBadge.svelte';
  import StderrLogButton from '../shared/StderrLogButton.svelte';
  import type { createGatewayStore } from '../state/gateway-store.svelte';

  let {
    row,
    gateway,
    grid
  }: {
    row: GatewayRow;
    gateway: ReturnType<typeof createGatewayStore>;
    grid: string;
  } = $props();
</script>

<div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={grid}>
  <span class="flex min-w-0 items-center gap-1.5">
    {#if row.is_default}
      <Star
        class="shrink-0 text-amber-500"
        fill="currentColor"
        size={15}
        title={`Default gateway: ${row.name}`}
      />
    {/if}
    <strong class="truncate font-sans text-sm">{row.name}</strong>
    <button
      class="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      type="button"
      onclick={() => gateway.openFolder(row)}
      title={`Open gateway folder: ${row.path}`}
      aria-label={`Open gateway folder: ${row.path}`}
    >
      <FolderOpen size={13} />
    </button>
  </span>
  <span class="space-y-1">
    <Badge variant={row.running ? 'success' : 'outline'}>
      {row.running ? 'Running' : 'Stopped'}
    </Badge>
    {#if row.pid && row.running}
      <small class="block text-xs text-muted-foreground">PID {row.pid}</small>
    {/if}
  </span>
  <span class="truncate text-xs text-muted-foreground">{row.host}:{row.port}</span>
  <span>
    <AutostartBadge method={row.autostart_method} />
  </span>
  <span class="flex flex-wrap gap-1.5">
    {#if !row.running}
      <Button size="sm" variant="outline" disabled={gateway.busy} onclick={() => gateway.start(row)}><Play size={13} /> Start</Button>
    {:else}
      <Button size="sm" variant="outline" disabled={gateway.busy} onclick={() => gateway.openStop(row)}><Square size={13} /> Stop</Button>
    {/if}
    <StderrLogButton
      exists={row.stderr_log_exists}
      recent={row.stderr_log_recent}
      mtime={row.stderr_log_mtime}
      size={row.stderr_log_size}
      onclick={() => gateway.openStderrLog(row)}
    />
    <Button size="sm" variant="destructive" onclick={() => gateway.openRemove(row)}><Trash2 size={13} /> Remove</Button>
  </span>
</div>
