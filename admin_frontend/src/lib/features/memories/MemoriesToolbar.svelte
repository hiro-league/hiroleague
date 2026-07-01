<script lang="ts">
  import { RefreshCw, Trash2 } from '@lucide/svelte';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import SearchInput from '$lib/search/SearchInput.svelte';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { ADMIN_INPUT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import type { MemoryFilterKey } from './shared/memory-pure';

  let {
    filters,
    setFilter,
    groupsForMemoryFilterDropdown = [],
    characterOptions,
    sourcesForMemoryFilterDropdown,
    canClearMemories,
    clearableMemoryCount,
    memoryActionBusy,
    memoriesLoading,
    onRequestClearMemories,
    onRequestClearGroup,
    onRefreshMemories
  }: {
    filters: Record<MemoryFilterKey, string>;
    setFilter: (key: MemoryFilterKey, value: string) => void;
    groupsForMemoryFilterDropdown?: { value: string; label: string }[];
    characterOptions: { value: string; label: string }[];
    sourcesForMemoryFilterDropdown: { value: string; label: string }[];
    /** Offer "Clear memories" (row filter active + relation facts in view). */
    canClearMemories: boolean;
    /** Relation-fact count "Clear memories" would delete (button label). */
    clearableMemoryCount: number;
    memoryActionBusy: boolean;
    memoriesLoading: boolean;
    onRequestClearMemories: () => void;
    onRequestClearGroup: () => void;
    onRefreshMemories: () => void;
  } = $props();
</script>

<AdminPageStickyToolbar>
  <div class="memories-controls">
    <AdminFilterBar class="min-w-0 flex-1 items-end">
      {#if groupsForMemoryFilterDropdown.length > 0}
        <!-- A single group is always selected — no "All" scope (it only ever meant conversation
             memory, never knowledge/eval, which was confusing). No placeholder option. -->
        <AdminFilterBarSelect
          label="Group"
          value={filters.mem_group}
          onValueChange={(v) => setFilter('mem_group', v)}
          class="min-w-[12rem]"
          options={groupsForMemoryFilterDropdown}
        />
      {/if}
      <AdminFilterBarSelect
        label="Character"
        value={filters.mem_char}
        onValueChange={(v) => setFilter('mem_char', v)}
        placeholder="All characters"
        class="min-w-[10rem]"
        options={characterOptions}
      />
      <AdminFilterBarSelect
        label="Source"
        value={filters.mem_source}
        onValueChange={(v) => setFilter('mem_source', v)}
        placeholder="All sources"
        class="min-w-[10rem]"
        options={sourcesForMemoryFilterDropdown}
      />
      <FormField label="From" class="min-w-[9rem]">
        <input
          type="date"
          class={cn(ADMIN_INPUT, 'w-full')}
          value={filters.mem_from}
          oninput={(e) => setFilter('mem_from', e.currentTarget.value)}
        />
      </FormField>
      <FormField label="To" class="min-w-[9rem]">
        <input
          type="date"
          class={cn(ADMIN_INPUT, 'w-full')}
          value={filters.mem_to}
          oninput={(e) => setFilter('mem_to', e.currentTarget.value)}
        />
      </FormField>
      <SearchInput
        label="Search"
        value={filters.mem_q}
        onValueChange={(v) => setFilter('mem_q', v)}
        placeholder="Search memory text, id, source…"
        class="min-w-[12rem] flex-1"
      />
    </AdminFilterBar>
    <div class="memories-actions">
      {#if canClearMemories}
        <!-- Deletes only the filtered relation facts in view (entities are excluded — use
             Clear group for those). Hidden when no row filter narrows the list. -->
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={memoryActionBusy || memoriesLoading}
          onclick={onRequestClearMemories}
          title="Delete the filtered facts currently shown"
        >
          <Trash2 size={14} aria-hidden="true" />
          Clear {clearableMemoryCount}
          {clearableMemoryCount === 1 ? 'memory' : 'memories'}
        </Button>
      {/if}
      {#if groupsForMemoryFilterDropdown.length > 0}
        <!-- Wipes the whole selected partition: facts + entities + episodes + communities. -->
        <Button
          type="button"
          variant="destructive"
          size="sm"
          disabled={memoryActionBusy || memoriesLoading}
          onclick={onRequestClearGroup}
          title="Delete the entire selected group (facts, entities, episodes)"
        >
          <Trash2 size={14} aria-hidden="true" />
          Clear group
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

<style>
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
</style>
