<script lang="ts">
  import type { ChatChannelRow } from '$lib/api/chat-channels';
  import type { CharacterRow } from '$lib/api/characters';
  import type { GraphLedgerRow } from '$lib/api/graph-runs';
  import GraphRunsListCharacterCell from './GraphRunsListCharacterCell.svelte';
  import { GRAPH_RUNS_PREVIEW_HIGHLIGHT_MARK } from './shared/graph-runs-ui';
  import GraphRunsTableShell from './view/GraphRunsTableShell.svelte';
  import {
    adminLogsUrlForInboundId,
    formatCost,
    formatGraphRunsListTs,
    formatRunListTokensCell,
    highlightPreviewSegments,
    listRowChannelName,
    listRowCharacter,
    GRAPH_RUNS_PANEL_IDS,
    GRAPH_RUNS_SUBTAB_IDS,
    trimRunIdForList
  } from './graph-runs-pure';

  /* Two-way binds for filters/search — Svelte 5 requires `$bindable()` defaults inside `$props()`, not standalone `let`. */
  let {
    filterCharacterId = $bindable(''),
    filterChannelId = $bindable(''),
    filterStatus = $bindable(''),
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
    onOpenRun
  }: {
    filterCharacterId?: string;
    filterChannelId?: string;
    filterStatus?: string;
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
  } = $props();
</script>

<div
  id={GRAPH_RUNS_PANEL_IDS.runs}
  class="flex min-w-0 flex-col gap-4"
  role="tabpanel"
  aria-labelledby={GRAPH_RUNS_SUBTAB_IDS.browse}
  {hidden}
>
  <div class="filters">
    <select bind:value={filterCharacterId} class="filter-select" aria-label="Filter by character">
      <option value="">All characters</option>
      {#each charactersForFilterDropdown as c (c.id)}
        <option value={c.id}>{c.name || c.id}</option>
      {/each}
    </select>
    <select bind:value={filterChannelId} class="filter-select" aria-label="Filter by channel">
      <option value="">All channels</option>
      {#each channelsForFilterDropdown as ch (ch.id)}
        <option value={String(ch.id)}>{ch.name || `Channel ${ch.id}`}</option>
      {/each}
    </select>
    <select bind:value={filterStatus} class="filter-select" aria-label="Filter by status">
      <option value="">All statuses</option>
      {#each statusesForFilterDropdown as st (st.value)}
        <option value={st.value}>{st.label}</option>
      {/each}
    </select>
    <input
      bind:value={previewSearch}
      class="preview-search"
      type="search"
      placeholder="Search input / output previews…"
      autocomplete="off"
    />
  </div>

  {#if error}
    <p class="error m-0" role="alert">{error}</p>
  {/if}

  <GraphRunsTableShell>
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Character</th>
          <th>Channel</th>
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
          {@const inputPreviewTooltip = String(row.input_preview ?? '').trim() ? String(row.input_preview ?? '') : undefined}
          {@const outputPreviewTooltip = String(row.output_preview ?? '').trim() ? String(row.output_preview ?? '') : undefined}
          <tr class:muted-open={openRunIds.includes(row.run_id)}>
            <td>{formatGraphRunsListTs(row.ts)}</td>
            <GraphRunsListCharacterCell photo={listCh.photo} name={listCh.name} />
            <td class="runs-list-name-cell">{listRowChannelName(row, channelById)}</td>
            <td>
              <button type="button" class="link" title={row.run_id} onclick={() => onOpenRun(row.run_id)}
                >{trimRunIdForList(row.run_id)}</button
              >
            </td>
            <td class="preview" title={inputPreviewTooltip}>
              {#if previewSearchNeedle && String(row.input_preview ?? '').toLowerCase().includes(previewSearchNeedle)}
                {#each highlightPreviewSegments(String(row.input_preview ?? ''), previewSearchNeedle) as seg, i (`${row.id}-in-${i}`)}
                  {#if seg.hit}<mark class={GRAPH_RUNS_PREVIEW_HIGHLIGHT_MARK}>{seg.text}</mark>{:else}{seg.text}{/if}
                {/each}
              {:else}
                {row.input_preview}
              {/if}
            </td>
            <td class="preview" title={outputPreviewTooltip}>
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
                  class="link"
                  href={adminLogsUrlForInboundId(row.inbound_id)}
                  title="Open Logs scoped to inbound message id (msg_id)"
                  >Logs</a
                >
              {:else}
                —
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </GraphRunsTableShell>
</div>

<style>
  button,
  input,
  select {
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 6px;
    background: var(--background, #fff);
    color: inherit;
    font: inherit;
  }

  input {
    min-width: 0;
    padding: 8px 10px;
  }

  select {
    min-width: 0;
    padding: 8px 10px;
    cursor: pointer;
  }

  .filter-select {
    flex: 0 1 200px;
    min-width: min(100%, 160px);
    max-width: 260px;
  }

  .filters {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    align-items: center;
  }

  .preview-search {
    flex: 1 1 280px;
    min-width: min(100%, 200px);
    max-width: 480px;
  }

  .runs-list-name-cell {
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .preview {
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .link {
    border: 0;
    background: transparent;
    color: var(--primary, #0369a1);
    padding: 0;
    cursor: pointer;
    font: inherit;
    text-decoration: none;
  }

  tr.muted-open {
    background: color-mix(in srgb, var(--accent, #0ea5e9) 8%, transparent);
  }

  .error {
    color: var(--muted-foreground, #64748b);
  }
</style>
