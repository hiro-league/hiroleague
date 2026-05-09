<script lang="ts">
  import { MessageSquare } from '@lucide/svelte';
  import { createCoreRowModel, createTable, type ColumnDef } from '@tanstack/svelte-table';
  import type { LogRow } from '$lib/api/logs';
  import { cn } from '$lib/utils';
  import LogExtraSegments from './LogExtraSegments.svelte';
  import LogLevelIcon from './shared/LogLevelIcon.svelte';
  import LogRowSourceIcon from './shared/LogRowSourceIcon.svelte';
  import type { LogsPageController } from './state/logs-controller.svelte';
  import { logLevelAccentClass, logModuleTextClass } from './shared/logs-classes';
  import {
    logRowSourceLabel,
    trafficClassChipClass,
    type RenderLogRow
  } from './shared/logs-ui';

  type Props = {
    ctrl: LogsPageController;
    /** When true, the Extra column is hidden (detail panel shows full extra payload). */
    detailPanelOpen: boolean;
    scroller?: HTMLDivElement | null;
    onSelectRow: (row: RenderLogRow) => void;
    onOpenRowDetails: (row: RenderLogRow) => void;
    onTableKeydown: (event: KeyboardEvent) => void;
    onFilterToMessage: (msgId: string, event: MouseEvent) => void;
  };

  let {
    ctrl,
    detailPanelOpen,
    scroller = $bindable(null),
    onSelectRow,
    onOpenRowDetails,
    onTableKeydown,
    onFilterToMessage
  }: Props = $props();

  const columnDefs: ColumnDef<any, LogRow, unknown>[] = [
    { id: '_msg_scope', accessorKey: '_msg_scope', header: '' },
    { id: 'date_display', accessorKey: 'date_display', header: 'Date' },
    { id: 'timestamp_display', accessorKey: 'timestamp_display', header: 'Time' },
    { id: 'level', accessorKey: 'level', header: 'Lvl' },
    { id: 'source', accessorKey: 'source', header: 'Source' },
    { id: 'module', accessorKey: 'module', header: 'Module' },
    { id: 'class', accessorKey: 'scope_traffic_class', header: 'Class' },
    { id: 'subclass', accessorKey: 'scope_traffic_subclass', header: 'Subclass' },
    { id: 'message', accessorKey: 'message', header: 'Message' },
    { id: 'extra', accessorKey: 'extra', header: 'Extra' }
  ];

  const table = createTable({
    get data() {
      return ctrl.visibleRows;
    },
    get columns() {
      return detailPanelOpen ? columnDefs.filter((c) => c.id !== 'extra') : columnDefs;
    },
    getCoreRowModel: createCoreRowModel(),
    getRowId: (row: RenderLogRow) => row._rowKey
  } as any);
</script>

<div class="min-h-0 min-w-0 flex-1 overflow-hidden rounded-md border bg-card/70">
  {#if ctrl.loading}
    <div class="grid h-full min-h-80 place-items-center font-sans text-sm text-muted-foreground">
      Loading logs...
    </div>
  {:else}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
    <div
      class="h-full overflow-auto outline-none"
      tabindex="0"
      role="application"
      aria-label="Log rows"
      bind:this={scroller}
      onkeydown={onTableKeydown}
    >
      <table
        class={cn(
          'w-full table-fixed border-collapse font-sans text-xs',
          detailPanelOpen ? 'min-w-[1180px]' : 'min-w-[1280px]'
        )}
      >
        <thead
          class="sticky top-0 z-10 border-b border-border/60 bg-muted/85 text-left text-foreground shadow-sm"
        >
          {#each table.getHeaderGroups() as headerGroup (headerGroup.id)}
            <tr>
              {#each headerGroup.headers as header (header.id)}
                <th
                  class={cn(
                    'px-2 py-2.5 text-[0.68rem] font-bold tracking-wide',
                    header.id === '_msg_scope' && 'w-[3.25rem] min-w-[3.25rem] px-0 text-center',
                    header.id === 'date_display' && 'w-[58px] text-center',
                    header.id === 'timestamp_display' && 'w-[76px] text-center',
                    header.id === 'source' && 'w-[136px]',
                    header.id === 'module' && 'w-[132px]',
                    header.id === 'class' && 'w-[110px]',
                    header.id === 'subclass' && 'w-[150px]',
                    header.id === 'level' && 'w-[34px] min-w-[34px] px-0 text-center',
                    header.id === 'message' && 'w-[380px]',
                    header.id === 'extra' && 'w-auto'
                  )}
                >
                  {String(header.column.columnDef.header ?? header.id)}
                </th>
              {/each}
            </tr>
          {/each}
        </thead>
        <tbody>
          {#each table.getRowModel().rows as tableRow (tableRow.id)}
            {@const row = tableRow.original as RenderLogRow}
            <tr
              class={cn(
                'cursor-default border-b border-border/60 transition-colors hover:bg-secondary/30',
                row.is_startup && '[&>td]:bg-primary/10',
                ctrl.activeRowKey === row._rowKey &&
                  'bg-primary/10 outline outline-1 outline-primary/30'
              )}
              data-active={ctrl.activeRowKey === row._rowKey ? 'true' : undefined}
              onclick={() => onSelectRow(row)}
              ondblclick={() => onOpenRowDetails(row)}
            >
              <td class="w-[3.25rem] min-w-[3.25rem] px-0 py-1 text-center align-middle">
                {#if row.scope_msg_id}
                  {@const msgOrd = ctrl.getScopeMsgOrdinal(row.scope_msg_id)}
                  {@const chipAlt = ctrl.getScopeMsgChipStripeAlt(row._rowKey)}
                  <div class="flex items-center justify-center gap-0.5">
                    {#if msgOrd != null}
                      <!-- Chip color alternates when the message # changes vs the previous scoped row (table order). -->
                      <span
                        class={cn(
                          'inline-flex min-h-4 min-w-[1rem] shrink-0 items-center justify-center rounded px-1 text-[0.6rem] font-semibold tabular-nums leading-none',
                          chipAlt
                            ? 'border border-border/70 bg-muted text-foreground'
                            : 'border border-primary/35 bg-primary/15 text-primary'
                        )}
                        title="Message #{msgOrd} in this session (stable while the logs page is open)"
                      >
                        {msgOrd}
                      </span>
                    {/if}
                    <button
                      type="button"
                      class="inline-grid shrink-0 place-items-center rounded-md p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
                      title={row.scope_text_preview?.trim()
                        ? `Message text: ${row.scope_text_preview} — Filter to this message`
                        : 'Filter to this message'}
                      onclick={(e) => onFilterToMessage(row.scope_msg_id!, e)}
                      ondblclick={(e) => e.stopPropagation()}
                    >
                      <MessageSquare size={14} strokeWidth={2} aria-hidden="true" />
                      <span class="sr-only">
                        Filter to message{msgOrd != null ? ` ${msgOrd}` : ''}
                      </span>
                    </button>
                  </div>
                {/if}
              </td>
              <td class="truncate px-2 py-1.5 text-center text-muted-foreground">
                {row.date_display}
              </td>
              <td class="truncate px-2 py-1.5 text-center text-muted-foreground">
                {row.timestamp_display}
              </td>
              <td
                class="w-[34px] min-w-[34px] px-0 py-1.5 text-center align-middle"
                title={row.level}
              >
                <LogLevelIcon
                  level={row.level}
                  size={14}
                  class={cn('inline-block', logLevelAccentClass(row.level))}
                />
              </td>
              <td
                class="truncate px-2 py-1.5"
                title={logRowSourceLabel(row.source) !== row.source ? row.source : undefined}
              >
                <span class="inline-flex max-w-full items-center gap-1">
                  <LogRowSourceIcon
                    rowSource={row.source}
                    size={13}
                    class="shrink-0 text-muted-foreground"
                  />
                  <span class="min-w-0 truncate font-normal text-foreground">
                    {logRowSourceLabel(row.source)}
                  </span>
                </span>
              </td>
              <td class="truncate px-2 py-1.5">
                <span class={logModuleTextClass(row.module)}>{row.module}</span>
              </td>
              <td class="truncate px-2 py-1.5">
                {#if row.scope_traffic_class}
                  <span
                    class={cn(
                      'inline-flex max-w-full items-center rounded-full border px-1.5 py-0.5 text-[0.6rem] font-medium leading-none',
                      trafficClassChipClass(row.scope_traffic_class)
                    )}
                    title={row.scope_traffic_class}
                  >
                    <span class="truncate">{row.scope_traffic_class}</span>
                  </span>
                {/if}
              </td>
              <td class="truncate px-2 py-1.5" title={row.scope_traffic_subclass}>
                {#if row.scope_traffic_subclass}
                  <span
                    class="font-mono text-[0.7rem] text-muted-foreground"
                  >{row.scope_traffic_subclass}</span>
                {/if}
              </td>
              <td class="truncate px-2 py-1.5" title={row.message}>
                {#if row.is_startup}
                  <span class="font-bold">{row.message}</span>
                {:else}
                  {row.message}
                {/if}
              </td>
              {#if !detailPanelOpen}
                <td class="group relative truncate px-2 py-1.5" title={row.extra}>
                  <LogExtraSegments segments={row.extra_segments} variant="table" />
                </td>
              {/if}
            </tr>
          {:else}
            <tr>
              <td
                colspan={detailPanelOpen ? 9 : 10}
                class="px-3 py-10 text-center text-muted-foreground"
              >
                No log rows match the current filters.
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
