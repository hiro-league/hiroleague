<script lang="ts">
  /**
   * Top control row for the knowledge graph view: type/relation filter strip (left) +
   * unified search box, Fit, Reload, and Fullscreen actions (right). Purely presentational
   * — it reads the model and calls back to the panel for engine-owned actions (fit / reload
   * / reframe / fullscreen). Search orchestration (debounce + backend lookup) lives in the
   * model; this just binds the input to graph.search / graph.clearSearch.
   */
  import { Search, X } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import type { KnowledgeGraphModel } from '../state/knowledge-graph.svelte';
  import KnowledgeGraphFilterBar from './KnowledgeGraphFilterBar.svelte';
  import MultiSelectFilter, {
    type MultiSelectOption
  } from '$lib/components/ui/multi-select-filter.svelte';

  interface Props {
    graph: KnowledgeGraphModel;
    fullscreen: boolean;
    /** Switch the viewed partition (knowledge vs a conversation-memory group). */
    onSelectGroup: (id: string) => void;
    /** Hand the camera back to auto-fit — called before a query change so a new/cleared
     *  search reframes onto its matches (engine.markIntentionalReframe in the panel). */
    onSearchReframe: () => void;
  }
  let { graph, fullscreen, onSelectGroup, onSearchReframe }: Props = $props();

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

  // Episode multi-select options, in corpus order (backend sorts by chunk_id). The episode ID
  // is the label — it's the stable identifier you actually select by (no numbering: one
  // timestamp can hold several episodes, so a positional "#n" would be misleading). The text
  // snippet stays searchable via `keywords`. `count` = graph items the episode contributes, so
  // graphless episodes visibly read 0.
  const episodeOptions = $derived<MultiSelectOption[]>(
    graph.episodes().map((ep) => ({
      value: ep.id,
      label: ep.id,
      keywords: ep.snippet,
      count: graph.episodeItemCount(ep.id)
    }))
  );
  function onEpisodesChange(ids: string[]): void {
    onSearchReframe(); // changing the episode filter reframes onto the new subgraph
    graph.setSelectedEpisodes(ids);
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
    {#if episodeOptions.length > 0}
      <!-- Episode filter: a scoping control (sibling of the partition selector). Selecting
           episodes feeds their chunk_ids into the SAME highlight/dim/hide focus pipeline as
           search, so it respects the current view setting. Shown only when the partition has
           episodes. -->
      <MultiSelectFilter
        label="Episodes"
        options={episodeOptions}
        selected={graph.selectedEpisodeIds()}
        onSelectedChange={onEpisodesChange}
        searchPlaceholder="Search episode id / text…"
      />
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
        <!-- Count + clear belong to the TEXT box, so gate on the query (not searchActive, which
             is also true on an episode-only selection — that would show a no-op X here). -->
        {#if graph.searchQuery().trim().length > 0}
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
    {/if}
  </div>
</div>
