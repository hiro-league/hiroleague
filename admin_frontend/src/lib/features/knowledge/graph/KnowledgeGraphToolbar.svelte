<script lang="ts">
  /**
   * Top control row for the knowledge graph view: type/relation filter strip (left) +
   * unified search box, Fit, Reload, and Fullscreen actions (right). Purely presentational
   * — it reads the model and calls back to the panel for engine-owned actions (fit / reload
   * / reframe / fullscreen). Search orchestration (debounce + backend lookup) lives in the
   * model; this just binds the input to graph.search / graph.clearSearch.
   */
  import { Maximize2, Minimize2, RefreshCw, Scan, Search, Trash2, X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';
  import type { KnowledgeGraphModel } from '../state/knowledge-graph.svelte';
  import KnowledgeGraphFilterBar from './KnowledgeGraphFilterBar.svelte';

  interface Props {
    graph: KnowledgeGraphModel;
    fullscreen: boolean;
    /** Fit the whole graph (or search subset) to view. */
    onFit: () => void;
    /** Reload the authoritative export (also reframes the camera). */
    onReload: () => void;
    /** Toggle the full-viewport overlay. */
    onToggleFullscreen: () => void;
    /** Open the "clear entire knowledge graph" confirm. */
    onClearGraph: () => void;
    /** Switch the viewed partition (knowledge vs a conversation-memory group). */
    onSelectGroup: (id: string) => void;
    /** Hand the camera back to auto-fit — called before a query change so a new/cleared
     *  search reframes onto its matches (engine.markIntentionalReframe in the panel). */
    onSearchReframe: () => void;
  }
  let {
    graph,
    fullscreen,
    onFit,
    onReload,
    onToggleFullscreen,
    onClearGraph,
    onSelectGroup,
    onSearchReframe
  }: Props = $props();

  // The knowledge partition's id (its option maps to the default view).
  const knowledgeGroupId = $derived(graph.groups().find((g) => g.kind === 'knowledge')?.id ?? '');

  function onSearchInput(value: string): void {
    onSearchReframe(); // a new query is an intentional reframe → re-enable focus fit
    graph.search(value);
  }
  function onClear(): void {
    onSearchReframe(); // clearing reframes (full set if 'hide' was relaying out)
    graph.clearSearch();
  }
</script>

<!-- Fullscreen → frosted bar with bottom border, like the shell header. Default → inline
     row with no chrome. Node/edge counts + live status live inside the canvas overlay. -->
<div
  class={cn(
    'flex items-center justify-between gap-3',
    fullscreen && 'border-b bg-background/85 px-4 py-2 backdrop-blur'
  )}
>
  <div class="min-w-0 flex-1">
    {#if graph.nodes().length > 0}
      <KnowledgeGraphFilterBar {graph} />
    {/if}
  </div>
  <div class="flex shrink-0 items-center gap-2">
    {#if graph.groups().length >= 1}
      <!-- Partition selector: lists whatever graph partitions exist (knowledge / conversation
           memory / eval), shown by logical name. Rendered whenever ≥1 partition is present so
           a single data-bearing group is never hidden. -->
      <select
        value={graph.activeGroupId() ?? knowledgeGroupId}
        onchange={(e) => onSelectGroup(e.currentTarget.value)}
        class="h-8 max-w-[12rem] rounded-md border bg-background px-2 text-xs text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
        aria-label="Graph partition"
        title="Choose which graph to view (knowledge or a conversation memory)"
      >
        {#each graph.groups() as g (g.id)}
          <option value={g.id}>{g.label}</option>
        {/each}
      </select>
    {/if}
    {#if graph.nodes().length > 0}
      <!-- Unified search: highlights matching nodes/edges (by name/alias, relation/fact, or
           chunk text) with an amber ring and frames them in view — never hides the rest. -->
      <div class="relative">
        <Search
          size={14}
          class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <input
          type="search"
          value={graph.searchQuery()}
          oninput={(e) => onSearchInput(e.currentTarget.value)}
          placeholder="Search graph…"
          aria-label="Search nodes, edges, and chunk text"
          class="h-8 w-44 rounded-md border bg-background pl-7 pr-16 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background sm:w-52 [&::-webkit-search-cancel-button]:hidden"
        />
        {#if graph.searchActive()}
          <div class="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-1.5">
            <span
              class="tabular-nums text-[10px] font-medium {graph.matchCount() > 0
                ? 'text-amber-600 dark:text-amber-400'
                : 'text-muted-foreground'}"
              title={`${graph.matchCount()} match${graph.matchCount() === 1 ? '' : 'es'}${graph.searchBusy() ? ' (searching chunks…)' : ''}`}
            >
              {graph.searchBusy() ? '…' : graph.matchCount()}
            </span>
            <button
              type="button"
              onclick={onClear}
              class="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
              aria-label="Clear search"
              title="Clear search"
            >
              <X size={13} aria-hidden="true" />
            </button>
          </div>
        {/if}
      </div>
      <!-- Fit to view: reframe the whole graph (or the search subset) on demand. -->
      <Button variant="outline" size="icon" onclick={onFit} aria-label="Fit graph to view" title="Fit to view">
        <Scan size={16} aria-hidden="true" />
      </Button>
    {/if}
    <Button variant="outline" size="sm" onclick={onReload} disabled={graph.loading()} title="Reload graph">
      <RefreshCw size={14} class={graph.loading() ? 'animate-spin' : ''} aria-hidden="true" />
      Reload
    </Button>
    {#if graph.nodes().length > 0}
      <!-- Clear graph: wipe ALL entities + facts (documents/chunks are kept so it can be
           rebuilt). Confirmed in a dialog owned by the panel. -->
      <Button
        variant="outline"
        size="sm"
        onclick={onClearGraph}
        disabled={graph.loading()}
        class="text-destructive hover:text-destructive"
        title="Delete the entire knowledge graph (keeps documents)"
      >
        <Trash2 size={14} aria-hidden="true" />
        Clear graph
      </Button>
    {/if}
    <Button
      variant="outline"
      size="icon"
      onclick={onToggleFullscreen}
      aria-label={fullscreen ? 'Exit full screen (Esc)' : 'View graph full screen'}
      title={fullscreen ? 'Exit full screen (Esc)' : 'Full screen'}
    >
      {#if fullscreen}
        <Minimize2 size={16} aria-hidden="true" />
      {:else}
        <Maximize2 size={16} aria-hidden="true" />
      {/if}
    </Button>
  </div>
</div>
