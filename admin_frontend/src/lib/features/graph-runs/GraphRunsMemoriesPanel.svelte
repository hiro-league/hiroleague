<script lang="ts">
  import { Eye, RefreshCw, Trash2 } from '@lucide/svelte';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import AdminFilterBarSearch from '$lib/components/page/table/AdminFilterBarSearch.svelte';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { ChatChannelRow } from '$lib/api/chat-channels';
  import type { CharacterRow } from '$lib/api/characters';
  import GraphRunsListCharacterCell from './GraphRunsListCharacterCell.svelte';
  import {
    graphRunsMemoriesTableShellClass,
    graphRunsNameCellClass
  } from './shared/graph-runs-table-ui';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import {
    memoryChannelName,
    memoryCharacter,
    memoryCreatedRaw,
    memoryDateDisplay,
    memoryId,
    memoryPrimaryText,
    memorySharedLabel,
    memorySourceLabel,
    memoryStableKey,
    memoryUpdatedRaw,
    GRAPH_RUNS_PANEL_IDS,
    GRAPH_RUNS_PRIMARY_TAB_IDS
  } from './graph-runs-pure';

  let {
    memorySearch = $bindable(''),
    memoryFilterCharacterId = $bindable(''),
    memoryFilterChannelId = $bindable(''),
    memoryFilterSource = $bindable(''),
    hidden,
    memoriesError,
    memoriesLoading,
    memoryEnabled,
    memoriesTotalCount,
    visibleMemoriesRows,
    charactersForFilterDropdown,
    channelsForMemoryFilterDropdown,
    sourcesForMemoryFilterDropdown,
    characterMap,
    channelById,
    memoryActionBusy,
    onRequestClearAll,
    onRefreshMemories,
    onViewJson,
    onDeleteRow
  }: {
    memorySearch?: string;
    memoryFilterCharacterId?: string;
    memoryFilterChannelId?: string;
    memoryFilterSource?: string;
    hidden: boolean;
    memoriesError: string;
    memoriesLoading: boolean;
    memoryEnabled: boolean | null;
    memoriesTotalCount: number;
    visibleMemoriesRows: Record<string, unknown>[];
    charactersForFilterDropdown: CharacterRow[];
    channelsForMemoryFilterDropdown: ChatChannelRow[];
    sourcesForMemoryFilterDropdown: { value: string; label: string }[];
    characterMap: Record<string, CharacterRow>;
    channelById: Map<number, ChatChannelRow>;
    memoryActionBusy: boolean;
    onRequestClearAll: () => void;
    onRefreshMemories: () => void;
    onViewJson: (row: Record<string, unknown>) => void;
    onDeleteRow: (row: Record<string, unknown>) => void;
  } = $props();

  const characterOptions = $derived(
    charactersForFilterDropdown.map((c) => ({ value: c.id, label: c.name || c.id }))
  );

  const channelOptions = $derived(
    channelsForMemoryFilterDropdown.map((ch) => ({
      value: String(ch.id),
      label: ch.name || `Channel ${ch.id}`
    }))
  );
</script>

<div
  id={GRAPH_RUNS_PANEL_IDS.memories}
  class="flex min-w-0 flex-col gap-4"
  role="tabpanel"
  aria-labelledby={GRAPH_RUNS_PRIMARY_TAB_IDS.memories}
  {hidden}
>
  {#if memoriesError}
    <p class="error m-0 font-sans text-sm text-muted-foreground" role="alert">{memoriesError}</p>
  {/if}

  <div class="memories-panel">
    {#if memoriesLoading}
      <InlineLoading label="Loading memories…" class="m-0" />
    {:else if memoryEnabled === false}
      <p class="memories-hint">
        Long-term memory is disabled or not configured for this workspace (preferences or missing models).
      </p>
    {:else if memoriesError}
      <!-- Error banner above -->
    {:else}
      {#if !hidden}
        <AdminPageStickyToolbar>
          <div class="memories-controls">
          <AdminFilterBar class="min-w-0 flex-1 items-end">
            <AdminFilterBarSelect
              label="Character"
              bind:value={memoryFilterCharacterId}
              placeholder="All characters"
              class="min-w-[10rem]"
              options={characterOptions}
            />
            <AdminFilterBarSelect
              label="Channel"
              bind:value={memoryFilterChannelId}
              placeholder="All channels"
              class="min-w-[10rem]"
              options={channelOptions}
            />
            <AdminFilterBarSelect
              label="Source"
              bind:value={memoryFilterSource}
              placeholder="All sources"
              class="min-w-[10rem]"
              options={sourcesForMemoryFilterDropdown}
            />
            <AdminFilterBarSearch
              label="Search"
              bind:value={memorySearch}
              placeholder="Search memory text, id, source…"
              class="min-w-[12rem] flex-1"
            />
          </AdminFilterBar>
          <div class="memories-actions">
            {#if memoriesTotalCount > 0}
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={memoryActionBusy || memoriesLoading}
                onclick={onRequestClearAll}
              >
                <Trash2 size={14} aria-hidden="true" />
                Clear all memories
              </Button>
            {/if}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              class="text-muted-foreground hover:text-foreground"
              disabled={memoriesLoading}
              aria-label="Refresh memories list"
              title="Refresh memories list"
              onclick={onRefreshMemories}
            >
              <RefreshCw
                size={17}
                strokeWidth={2}
                class={memoriesLoading ? 'motion-safe:animate-spin' : ''}
                aria-hidden="true"
              />
            </Button>
          </div>
          </div>
        </AdminPageStickyToolbar>
      {/if}

      {#if memoriesTotalCount === 0}
        <p class="memories-hint">No memories in the store for the default user yet.</p>
      {:else if visibleMemoriesRows.length === 0}
        <p class="memories-hint">No memories match the current filters.</p>
      {:else}
        <AdminTableShell density="dense" stickyHead class={graphRunsMemoriesTableShellClass}>
          <thead>
            <tr>
              <th>Updated</th>
              <th>Created</th>
              <th>Character</th>
              <th>Channel</th>
              <th>Memory</th>
              <th>Shared</th>
              <th>Source</th>
              <th>Id</th>
              <th>Payload</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each visibleMemoriesRows as row, idx (memoryStableKey(row, idx))}
              {@const updated = memoryDateDisplay(memoryUpdatedRaw(row))}
              {@const created = memoryDateDisplay(memoryCreatedRaw(row))}
              {@const memCharacter = memoryCharacter(row, characterMap, channelById)}
              <tr>
                <td class="memories-date-cell" title={updated.title}>
                  <span>{updated.date}</span>
                  <span>{updated.time}</span>
                </td>
                <td class="memories-date-cell" title={created.title}>
                  <span>{created.date}</span>
                  <span>{created.time}</span>
                </td>
                <GraphRunsListCharacterCell photo={memCharacter.photo} name={memCharacter.name} />
                <td class={graphRunsNameCellClass}>{memoryChannelName(row, channelById)}</td>
                <td class="memories-text-cell">{memoryPrimaryText(row)}</td>
                <td>{memorySharedLabel(row)}</td>
                <td>{memorySourceLabel(row)}</td>
                <td class="font-mono memories-id-cell">{memoryId(row) || '—'}</td>
                <td class="memories-payload-cell">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    class="h-7 gap-1 px-2 text-xs shadow-none"
                    onclick={() => onViewJson(row)}
                  >
                    <Eye size={14} aria-hidden="true" />
                    View JSON
                  </Button>
                </td>
                <td class="memories-actions-cell">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    class="size-[30px] text-muted-foreground hover:text-destructive"
                    disabled={memoryActionBusy || !memoryId(row)}
                    title={memoryId(row) ? 'Delete memory' : 'Cannot delete: missing memory id'}
                    aria-label="Delete memory"
                    onclick={() => onDeleteRow(row)}
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </Button>
                </td>
              </tr>
            {/each}
          </tbody>
        </AdminTableShell>
      {/if}
    {/if}
  </div>
</div>

<style>
  .memories-panel {
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-height: 120px;
  }

  .memories-hint {
    margin: 0;
    font-size: 14px;
    color: var(--muted-foreground, #64748b);
  }

  .memories-controls {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 12px;
    row-gap: 12px;
  }

  .memories-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 10px;
    flex: 0 0 auto;
    margin-left: auto;
  }

  .memories-date-cell {
    min-width: 86px;
    white-space: nowrap;
    color: var(--muted-foreground, #64748b);
  }

  .memories-date-cell span {
    display: block;
    line-height: 1.35;
  }

  .memories-text-cell {
    max-width: min(480px, 40vw);
    white-space: normal;
    word-break: break-word;
  }

  .memories-id-cell {
    max-width: 140px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .memories-payload-cell {
    vertical-align: top;
    min-width: 100px;
  }

  .memories-actions-cell {
    text-align: center;
    min-width: 64px;
  }

  :global(.admin-table-shell-dense.memories-table-wrap) :global(table) {
    white-space: normal;
    min-width: 1120px;
  }
</style>
