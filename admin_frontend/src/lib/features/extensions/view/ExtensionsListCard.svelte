<script lang="ts">
  import { Link2, Link2Off, PlugZap, RefreshCw } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import Panel from '$kit/ui/panel.svelte';
  import ResourceView from '$kit/ui/resource-view.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import { dateTime } from '$lib/format/time';
  import type { ExtensionsController } from '../state/extensions-controller.svelte';

  let { ctrl }: { ctrl: ExtensionsController } = $props();

  const GRID = '170px 110px 1.4fr 190px 240px';
  // ResourceView's shape: nothing to show yet reads as loading / failed; rows already held stay up while it reloads.
  const view = $derived({
    data: ctrl.rows.length || !(ctrl.loading || ctrl.error) ? ctrl.rows : null,
    error: ctrl.error ?? '',
    loading: ctrl.loading,
    reload: () => ctrl.load()
  });
</script>

<Panel class="grid gap-4">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class="text-lg font-semibold">Add an extension</h3>
      <p class="font-sans text-sm text-muted-foreground">
        Make a short-lived code, then type it with the address into the extension's settings
        (HomeHiro: Settings, HiroLeague).
      </p>
    </div>
    <Button disabled={ctrl.busy} onclick={() => void ctrl.generatePairingCode()}>
      <Link2 size={15} /> Make a pairing code
    </Button>
  </div>
</Panel>

<Panel title="Paired extensions" description={`${ctrl.connectedCount} of ${ctrl.rows.length} connected`} class="grid gap-4">
  {#snippet actions()}
    <Button variant="outline" disabled={ctrl.loading} onclick={() => void ctrl.load()}>
      <RefreshCw size={15} /> Refresh
    </Button>
  {/snippet}
  <ResourceView
    resource={view}
    loadingLabel="Loading extensions…"
    errorTitle="Could not load extensions"
    empty={(d) => d.length === 0}
    emptyMessage="No extensions yet. Make a pairing code above to add one."
    quiet
  >
    {#snippet children()}
      <TableShell layout="grid" minWidth={900} gridColumns={GRID} stickyHead>
        {#snippet headRow()}
          <span>Name</span>
          <span>Version</span>
          <span>Status</span>
          <span>Paired</span>
          <span>Actions</span>
        {/snippet}
        {#snippet body()}
          {#each ctrl.rows as row (row.extension_id)}
            <div class={TABLE_GRID_ROW} style:grid-template-columns={GRID}>
              <span class="truncate font-sans text-sm font-semibold" title={row.extension_id}>
                {row.name || row.extension_id.slice(0, 12)}
              </span>
              <span class="truncate font-mono text-xs text-muted-foreground">{row.version || '—'}</span>
              <span class="grid gap-1">
                <span class="flex items-center gap-2">
                  {#if row.connected}
                    <Badge variant="success">Connected</Badge>
                    <span class="truncate text-xs text-muted-foreground" title={row.remote ?? ''}>
                      since {row.connected_at ? dateTime(row.connected_at) : '—'}
                    </span>
                  {:else}
                    <Badge variant="secondary">Not connected</Badge>
                    <span class="truncate text-xs text-muted-foreground">
                      last seen {row.last_seen ? dateTime(row.last_seen) : '—'}
                    </span>
                  {/if}
                </span>
                {#if ctrl.testResults[row.extension_id]}
                  <span class="truncate text-xs text-muted-foreground">{ctrl.testResults[row.extension_id]}</span>
                {/if}
              </span>
              <span class="truncate text-xs text-muted-foreground">{row.paired_at ? dateTime(row.paired_at) : '—'}</span>
              <span class="flex justify-end gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={ctrl.busy || !row.connected}
                  onclick={() => void ctrl.testCall(row)}
                  title="Ask the extension for its name and version"
                >
                  <PlugZap size={13} /> Test call
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={ctrl.busy}
                  onclick={() => ctrl.openRemove(row)}
                  title="Remove extension"
                >
                  <Link2Off size={13} /> Remove
                </Button>
              </span>
            </div>
          {/each}
        {/snippet}
      </TableShell>
    {/snippet}
  </ResourceView>
</Panel>
