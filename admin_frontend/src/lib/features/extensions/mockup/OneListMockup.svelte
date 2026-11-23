<script lang="ts">
  // mockup: the one list of every extension, channels and apps alike (Unified communication, phase 2).
  import { Download, Link2, Link2Off, Lock, Settings2 } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import { Switch } from '$kit/components/ui/switch/index.js';
  import MockupBadge from '$kit/ui/mockup-badge.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import EmptyState from '$kit/ui/empty-state.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import { dateTime } from '$kit/format/time';
  import { statusOf } from './one-list-mock';
  import type { OneListMockup } from './one-list-mockup.svelte';

  interface Props {
    list: OneListMockup;
    /** Adding an app is today's pairing code, as it is. */
    onAddApp: () => void;
    addingApp: boolean;
  }
  let { list, onAddApp, addingApp }: Props = $props();

  const GRID = '1.6fr 100px 80px 1.3fr 190px';
</script>

<Panel
  title="Channels and apps"
  description={`${list.connectedCount} of ${list.rows.length} connected`}
  class="grid gap-4"
>
  {#snippet actions()}
    <MockupBadge title="A mockup of the one list: mock rows, and its switches and buttons change nothing" />
    <Button variant="outline" onclick={() => list.notYet('pick a channel to install, from those not installed yet')}>
      <Download size={15} /> Install a channel
    </Button>
    <Button disabled={addingApp} onclick={onAddApp}>
      <Link2 size={15} /> Add an app
    </Button>
  {/snippet}

  {#if list.rows.length === 0}
    <EmptyState message="Nothing is plugged in yet. Add an app with a pairing code, or install a channel." />
  {:else}
    <TableShell layout="grid" minWidth={820} gridColumns={GRID} stickyHead>
      {#snippet headRow()}
        <span>Name</span>
        <span>Kind</span>
        <span>Version</span>
        <span>Status</span>
        <span class="text-right">Actions</span>
      {/snippet}
      {#snippet body()}
        {#each list.rows as row (row.extension_id)}
          {@const status = statusOf(row)}
          <div class={TABLE_GRID_ROW} style:grid-template-columns={GRID}>
            <button
              type="button"
              class="grid min-w-0 text-left"
              onclick={() => list.open(row)}
              title="Open {row.label}"
            >
              <span class="truncate font-sans text-sm font-semibold">{row.label}</span>
              <span class="truncate text-xs text-muted-foreground">{row.description}</span>
            </button>
            <span>
              <Badge variant={row.kind === 'channel' ? 'secondary' : 'outline'}>
                {row.kind === 'channel' ? 'Channel' : 'App'}
              </Badge>
            </span>
            <span class="truncate font-mono text-xs text-muted-foreground">{row.version}</span>
            <span class="grid min-w-0 gap-0.5">
              <span class="flex items-center gap-2 text-sm">
                <StatusDot tone={status.tone} />
                {status.text}
              </span>
              <span class="truncate text-xs text-muted-foreground">
                {#if row.enabled === false}
                  switched off {dateTime(row.since)}
                {:else if row.connected}
                  since {dateTime(row.since)}
                {:else}
                  last seen {dateTime(row.since)}
                {/if}
              </span>
            </span>
            <span class="flex items-center justify-end gap-1.5">
              {#if row.started_by_core}
                {#if row.mandatory}
                  <span class="inline-flex size-8 items-center justify-center text-muted-foreground" title="Phones' chat needs it: it can't be switched off">
                    <Lock size={14} />
                  </span>
                {:else}
                  <Switch
                    checked={row.enabled === true}
                    onCheckedChange={() => list.toggle(row)}
                    tone="success"
                    aria-label={row.enabled ? `Switch ${row.label} off` : `Switch ${row.label} on`}
                    title={row.enabled ? 'On: the core runs it' : 'Off: the core does not start it'}
                    class="mx-2"
                  />
                {/if}
              {/if}
              <Button size="sm" variant="outline" onclick={() => list.open(row)} title="Open {row.label}">
                <Settings2 size={13} /> Manage
              </Button>
              <Button
                size="icon"
                variant="ghost"
                disabled={row.mandatory}
                onclick={() => void list.remove(row)}
                title={row.mandatory ? "Phones' chat needs it: it can't be removed" : `Remove ${row.label}`}
                aria-label="Remove {row.label}"
              >
                <Link2Off size={15} />
              </Button>
            </span>
          </div>
        {/each}
      {/snippet}
    </TableShell>
  {/if}
</Panel>
