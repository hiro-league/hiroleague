<script lang="ts">
  import { Eye, MessagesSquare, RefreshCw, Trash2 } from '@lucide/svelte';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import AdminFilterBarSearch from '$lib/components/page/table/AdminFilterBarSearch.svelte';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import AdminAvatarNameCell from '$lib/components/page/table/AdminAvatarNameCell.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { ADMIN_INPUT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import type { ChatChannelRow } from '$lib/api/chat-channels';
  import type { CharacterRow } from '$lib/api/characters';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import {
    memoryCharacter,
    memoryChunkIds,
    memoryCreatedRaw,
    memoryDateDisplay,
    memoryEntities,
    memoryGroupId,
    memoryId,
    memoryKind,
    memoryKindLabel,
    memoryPrimaryText,
    memoryStableKey,
    memoryValidity
  } from './shared/memory-pure';
  import { MEMORIES_A11Y } from './shared/memories-a11y';

  let {
    memorySearch = $bindable(''),
    memoryFilterGroupId = $bindable(''),
    memoryFilterCharacterId = $bindable(''),
    memoryFilterSource = $bindable(''),
    memoryFilterDateFrom = $bindable(''),
    memoryFilterDateTo = $bindable(''),
    hidden,
    memoriesError,
    memoriesLoading,
    memoryEnabled,
    memoriesTotalCount,
    visibleMemoriesRows,
    charactersForFilterDropdown,
    groupsForMemoryFilterDropdown = [],
    sourcesForMemoryFilterDropdown,
    characterMap,
    channelById,
    groupLabelById,
    memoryActionBusy,
    onRequestClearAll,
    onRefreshMemories,
    onViewJson,
    onViewProvenance
  }: {
    memorySearch?: string;
    memoryFilterGroupId?: string;
    memoryFilterCharacterId?: string;
    memoryFilterSource?: string;
    memoryFilterDateFrom?: string;
    memoryFilterDateTo?: string;
    hidden: boolean;
    memoriesError: string;
    memoriesLoading: boolean;
    memoryEnabled: boolean | null;
    memoriesTotalCount: number;
    visibleMemoriesRows: Record<string, unknown>[];
    charactersForFilterDropdown: CharacterRow[];
    /** Graph partitions for the Group selector (memory / knowledge / eval), like the Graph tab. */
    groupsForMemoryFilterDropdown?: { value: string; label: string }[];
    sourcesForMemoryFilterDropdown: { value: string; label: string }[];
    characterMap: Record<string, CharacterRow>;
    channelById: Map<number, ChatChannelRow>;
    /** group_id → logical label (Knowledge / Memory · char / Eval · …) for the Group column. */
    groupLabelById: Map<string, string>;
    memoryActionBusy: boolean;
    onRequestClearAll: () => void;
    onRefreshMemories: () => void;
    onViewJson: (row: Record<string, unknown>) => void;
    onViewProvenance: (row: Record<string, unknown>) => void;
  } = $props();

  const characterOptions = $derived(
    charactersForFilterDropdown.map((c) => ({ value: c.id, label: c.name || c.id }))
  );
</script>

<div
  id={MEMORIES_A11Y.memoriesPanel}
  class="flex min-w-0 flex-col gap-4"
  role="tabpanel"
  aria-labelledby={MEMORIES_A11Y.memoriesTab}
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
        Long-term memory is disabled or not configured for this workspace (settings or missing models).
      </p>
    {:else if memoriesError}
      <!-- Error banner above -->
    {:else}
      {#if !hidden}
        <AdminPageStickyToolbar>
          <div class="memories-controls">
          <AdminFilterBar class="min-w-0 flex-1 items-end">
            {#if groupsForMemoryFilterDropdown.length > 0}
              <AdminFilterBarSelect
                label="Group"
                bind:value={memoryFilterGroupId}
                placeholder="All memory"
                class="min-w-[12rem]"
                options={groupsForMemoryFilterDropdown}
              />
            {/if}
            <AdminFilterBarSelect
              label="Character"
              bind:value={memoryFilterCharacterId}
              placeholder="All characters"
              class="min-w-[10rem]"
              options={characterOptions}
            />
            <AdminFilterBarSelect
              label="Source"
              bind:value={memoryFilterSource}
              placeholder="All sources"
              class="min-w-[10rem]"
              options={sourcesForMemoryFilterDropdown}
            />
            <FormField label="From" class="min-w-[9rem]">
              <input type="date" class={cn(ADMIN_INPUT, 'w-full')} bind:value={memoryFilterDateFrom} />
            </FormField>
            <FormField label="To" class="min-w-[9rem]">
              <input type="date" class={cn(ADMIN_INPUT, 'w-full')} bind:value={memoryFilterDateTo} />
            </FormField>
            <AdminFilterBarSearch
              label="Search"
              bind:value={memorySearch}
              placeholder="Search memory text, id, source…"
              class="min-w-[12rem] flex-1"
            />
          </AdminFilterBar>
          <div class="memories-actions">
            {#if visibleMemoriesRows.length > 0}
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={memoryActionBusy || memoriesLoading}
                onclick={onRequestClearAll}
                title="Delete the memories matching the current filters"
              >
                <Trash2 size={14} aria-hidden="true" />
                Clear {visibleMemoriesRows.length}
                {visibleMemoriesRows.length === 1 ? 'memory' : 'memories'}
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
        <AdminTableShell density="dense" stickyHead class="memories-table-wrap">
          <thead>
            <tr>
              <th>Kind</th>
              <th>Created</th>
              <th>Validity</th>
              <th>Character</th>
              <th>Memory</th>
              <th>Entities</th>
              <th>Group</th>
              <th>Origin</th>
              <th>Id</th>
              <th>Payload</th>
            </tr>
          </thead>
          <tbody>
            {#each visibleMemoriesRows as row, idx (memoryStableKey(row, idx))}
              {@const kind = memoryKind(row)}
              {@const created = memoryDateDisplay(memoryCreatedRaw(row))}
              {@const validity = memoryValidity(row)}
              {@const invalidDisp = memoryDateDisplay(validity.invalidAt)}
              {@const entities = memoryEntities(row)}
              {@const groupLabel = groupLabelById.get(memoryGroupId(row)) || memoryGroupId(row)}
              {@const chunkCount = memoryChunkIds(row).length}
              {@const memCharacter = memoryCharacter(row, characterMap, channelById)}
              <tr>
                <td>
                  {#if kind}
                    <Badge variant={kind === 'relation' ? 'secondary' : 'outline'}>
                      {memoryKindLabel(row)}
                    </Badge>
                  {:else}
                    —
                  {/if}
                </td>
                <td class="memories-date-cell" title={created.title}>
                  <span>{created.date}</span>
                  <span>{created.time}</span>
                </td>
                <td>
                  {#if validity.expired}
                    <Badge
                      variant="warning"
                      title={`Stopped being true on ${invalidDisp.title || invalidDisp.date}`}
                    >
                      Expired{invalidDisp.date !== '—' ? ` ${invalidDisp.date}` : ''}
                    </Badge>
                  {:else}
                    <Badge variant="success">Current</Badge>
                  {/if}
                </td>
                <AdminAvatarNameCell photo={memCharacter.photo} name={memCharacter.name} />
                <td class="memories-text-cell">{memoryPrimaryText(row)}</td>
                <td class="memories-entities-cell">
                  {#if entities && entities.kind === 'relation'}
                    <span class="memories-entity">{entities.source}</span>
                    {#if entities.relation}
                      <span class="memories-rel">—[{entities.relation}]→</span>
                    {:else}
                      <span class="memories-rel">→</span>
                    {/if}
                    <span class="memories-entity">{entities.target}</span>
                  {:else if entities && entities.kind === 'summary'}
                    <span class="memories-entity">{entities.entity || '—'}</span>
                    {#if entities.type}
                      <span class="memories-rel">({entities.type})</span>
                    {/if}
                  {:else}
                    —
                  {/if}
                </td>
                <td class="memories-group-cell" title={groupLabel}>{groupLabel || '—'}</td>
                <td class="memories-origin-cell">
                  {#if chunkCount > 0}
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      class="h-7 gap-1 px-2 text-xs shadow-none"
                      title="View the conversation turn(s) this fact came from"
                      onclick={() => onViewProvenance(row)}
                    >
                      <MessagesSquare size={14} aria-hidden="true" />
                      {chunkCount}
                      {chunkCount === 1 ? 'turn' : 'turns'}
                    </Button>
                  {:else}
                    —
                  {/if}
                </td>
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

  .memories-entities-cell {
    max-width: 260px;
    white-space: normal;
    word-break: break-word;
    line-height: 1.4;
  }

  .memories-entity {
    font-weight: 600;
  }

  .memories-rel {
    margin: 0 4px;
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 11px;
    color: var(--muted-foreground, #64748b);
  }

  .memories-group-cell {
    max-width: 180px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted-foreground, #64748b);
  }

  .memories-origin-cell {
    min-width: 90px;
    white-space: nowrap;
  }

  .memories-payload-cell {
    vertical-align: top;
    min-width: 100px;
  }

  :global(.admin-table-shell-dense.memories-table-wrap) :global(table) {
    white-space: normal;
    min-width: 1180px;
  }
</style>
