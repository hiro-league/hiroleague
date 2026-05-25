<script lang="ts">
  import type { ChatChannelRow } from '$lib/api/chat-channels';
  import type { CharacterRow } from '$lib/api/characters';
  import type { GraphLedgerRow } from '$lib/api/graph-runs';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import AdminFilterBarSearch from '$lib/components/page/table/AdminFilterBarSearch.svelte';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import GraphRunsListCharacterCell from './GraphRunsListCharacterCell.svelte';
  import { GRAPH_RUNS_PREVIEW_HIGHLIGHT_MARK } from './shared/graph-runs-ui';
  import {
    graphRunsNameCellClass,
    graphRunsPreviewCellClass,
    graphRunsTableLinkClass
  } from './shared/graph-runs-table-ui';
  import {
    adminLogsUrlForInboundId,
    formatCost,
    formatGraphRunsListTs,
    formatRunListTokensCell,
    graphRunKindLabel,
    highlightPreviewSegments,
    listRowChannelName,
    listRowCharacter,
    GRAPH_RUNS_PANEL_IDS,
    GRAPH_RUNS_SUBTAB_IDS,
    trimRunIdForList,
    type GraphRunKindFilter
  } from './graph-runs-pure';

  let {
    filterCharacterId = $bindable(''),
    filterChannelId = $bindable(''),
    filterStatus = $bindable(''),
    filterRunKind = $bindable('' as GraphRunKindFilter),
    previewSearch = $bindable(''),
    hidden,
    error,
    visibleRows,
    openRunIds,
    previewSearchNeedle,
    charactersForFilterDropdown,
    channelsForFilterDropdown,
    statusesForFilterDropdown,
    characterMap,
    channelById,
    onOpenRun,
    hasMoreRuns = false,
    loadingMoreRuns = false,
    onLoadMore
  }: {
    filterCharacterId?: string;
    filterChannelId?: string;
    filterStatus?: string;
    filterRunKind?: GraphRunKindFilter;
    previewSearch?: string;
    hidden: boolean;
    error: string;
    visibleRows: GraphLedgerRow[];
    openRunIds: string[];
    previewSearchNeedle: string;
    charactersForFilterDropdown: CharacterRow[];
    channelsForFilterDropdown: ChatChannelRow[];
    statusesForFilterDropdown: { value: string; label: string }[];
    characterMap: Record<string, CharacterRow>;
    channelById: Map<number, ChatChannelRow>;
    onOpenRun: (runId: string) => void;
    hasMoreRuns?: boolean;
    loadingMoreRuns?: boolean;
    onLoadMore?: () => void;
  } = $props();

  const runKindOptions = [
    { value: 'chat', label: 'Chat agent' },
    { value: 'knowledge', label: 'Knowledge (standalone)' }
  ];

  const characterOptions = $derived(
    charactersForFilterDropdown.map((c) => ({ value: c.id, label: c.name || c.id }))
  );

  const channelOptions = $derived(
    channelsForFilterDropdown.map((ch) => ({
      value: String(ch.id),
      label: ch.name || `Channel ${ch.id}`
    }))
  );
</script>

<div
  id={GRAPH_RUNS_PANEL_IDS.runs}
  class="flex min-w-0 flex-col gap-4"
  role="tabpanel"
  aria-labelledby={GRAPH_RUNS_SUBTAB_IDS.browse}
  {hidden}
>
  <AdminFilterBar class="items-end">
    <AdminFilterBarSelect
      label="Run kind"
      bind:value={filterRunKind}
      placeholder="All run kinds"
      class="min-w-[10rem]"
      options={runKindOptions}
    />
    <AdminFilterBarSelect
      label="Character"
      bind:value={filterCharacterId}
      placeholder="All characters"
      class="min-w-[10rem]"
      options={characterOptions}
    />
    <AdminFilterBarSelect
      label="Channel"
      bind:value={filterChannelId}
      placeholder="All channels"
      class="min-w-[10rem]"
      options={channelOptions}
    />
    <AdminFilterBarSelect
      label="Status"
      bind:value={filterStatus}
      placeholder="All statuses"
      class="min-w-[10rem]"
      options={statusesForFilterDropdown}
    />
    <AdminFilterBarSearch
      label="Preview search"
      bind:value={previewSearch}
      placeholder="Search input / output previews…"
      class="min-w-[12rem] flex-1"
    />
  </AdminFilterBar>

  {#if error}
    <p class="error m-0 font-sans text-sm text-muted-foreground" role="alert">{error}</p>
  {/if}

  <AdminTableShell density="dense" stickyHead>
    <thead>
      <tr>
        <th>Time</th>
        <th>Character</th>
        <th>Channel</th>
        <th>Kind</th>
        <th>Run</th>
        <th>Input</th>
        <th>Output</th>
        <th>Status</th>
        <th>Cost</th>
        <th>Model</th>
        <th>Tokens</th>
        <th>Logs</th>
      </tr>
    </thead>
    <tbody>
      {#each visibleRows as row (row.id)}
        {@const listCh = listRowCharacter(row, characterMap, channelById)}
        {@const inputPreviewTooltip = String(row.input_preview ?? '').trim()
          ? String(row.input_preview ?? '')
          : undefined}
        {@const outputPreviewTooltip = String(row.output_preview ?? '').trim()
          ? String(row.output_preview ?? '')
          : undefined}
        <tr class:muted-open={openRunIds.includes(row.run_id)}>
          <td>{formatGraphRunsListTs(row.ts)}</td>
          <GraphRunsListCharacterCell photo={listCh.photo} name={listCh.name} />
          <td class={graphRunsNameCellClass}>{listRowChannelName(row, channelById)}</td>
          <td class="font-mono" title={row.run_id}>{graphRunKindLabel(row.run_id)}</td>
          <td>
            <button
              type="button"
              class={graphRunsTableLinkClass}
              title={row.run_id}
              onclick={() => onOpenRun(row.run_id)}
            >
              {trimRunIdForList(row.run_id)}
            </button>
          </td>
          <td class={graphRunsPreviewCellClass} title={inputPreviewTooltip}>
            {#if previewSearchNeedle && String(row.input_preview ?? '').toLowerCase().includes(previewSearchNeedle)}
              {#each highlightPreviewSegments(String(row.input_preview ?? ''), previewSearchNeedle) as seg, i (`${row.id}-in-${i}`)}
                {#if seg.hit}<mark class={GRAPH_RUNS_PREVIEW_HIGHLIGHT_MARK}>{seg.text}</mark>{:else}{seg.text}{/if}
              {/each}
            {:else}
              {row.input_preview}
            {/if}
          </td>
          <td class={graphRunsPreviewCellClass} title={outputPreviewTooltip}>
            {#if previewSearchNeedle && String(row.output_preview ?? '').toLowerCase().includes(previewSearchNeedle)}
              {#each highlightPreviewSegments(String(row.output_preview ?? ''), previewSearchNeedle) as seg, i (`${row.id}-out-${i}`)}
                {#if seg.hit}<mark class={GRAPH_RUNS_PREVIEW_HIGHLIGHT_MARK}>{seg.text}</mark>{:else}{seg.text}{/if}
              {/each}
            {:else}
              {row.output_preview}
            {/if}
          </td>
          <td>{row.status}</td>
          <td>{formatCost(row.cost_usd)}</td>
          <td>{row.model}</td>
          <td>{formatRunListTokensCell(row)}</td>
          <td>
            {#if String(row.inbound_id ?? '').trim()}
              <a
                class={graphRunsTableLinkClass}
                href={adminLogsUrlForInboundId(row.inbound_id)}
                title="Open Logs scoped to inbound message id (msg_id)"
              >
                Logs
              </a>
            {:else}
              —
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </AdminTableShell>

  {#if hasMoreRuns && onLoadMore}
    <div class="border-t py-3 text-center">
      <Button variant="outline" size="sm" disabled={loadingMoreRuns} onclick={() => onLoadMore()}>
        {loadingMoreRuns ? 'Loading…' : 'Load more runs'}
      </Button>
    </div>
  {/if}
</div>

<style>
  tr.muted-open {
    background: color-mix(in srgb, var(--accent) 8%, transparent);
  }

  .error {
    color: var(--muted-foreground, #64748b);
  }
</style>
