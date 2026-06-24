<script lang="ts">
  import SearchInput from '$lib/search/SearchInput.svelte';
  import EvalCorpusExtractionFilters from '$lib/features/eval/view/corpus-review/EvalCorpusExtractionFilters.svelte';
  import type { CorpusExtractionFilters } from '$lib/features/eval/state/eval-corpus-extraction-filters.svelte';

  interface Props {
    stickyTop: string;
    search: string;
    onSearchChange: (v: string) => void;
    filters: CorpusExtractionFilters;
    hasExtraction: boolean;
    markdownMode: boolean;
    onToggleMarkdown: () => void;
    searching: boolean;
    countFilterActive: boolean;
    filteredCount: number;
    totalCount: number;
    currentNo: number | null;
    onExpandAll: () => void;
    onCollapseAll: () => void;
  }

  let {
    stickyTop,
    search,
    onSearchChange,
    filters,
    hasExtraction,
    markdownMode,
    onToggleMarkdown,
    searching,
    countFilterActive,
    filteredCount,
    totalCount,
    currentNo,
    onExpandAll,
    onCollapseAll
  }: Props = $props();
</script>

<div
  class="sticky z-10 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border bg-background px-3 py-2 backdrop-blur supports-[backdrop-filter]:bg-background/90"
  style="top: {stickyTop};"
>
  <SearchInput
    variant="inline"
    class="h-8 w-48 min-w-0 shadow-xs"
    inputClass="text-xs"
    placeholder="Search episodes…"
    value={search}
    onValueChange={onSearchChange}
  />
  {#if hasExtraction}
    <EvalCorpusExtractionFilters {filters} />
  {/if}
  <span class="mx-0.5 h-4 w-px bg-border" aria-hidden="true"></span>
  <button
    type="button"
    class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 {markdownMode ? 'border-primary/40 bg-primary/10 font-medium text-primary' : ''}"
    aria-pressed={markdownMode}
    disabled={searching}
    title={searching
      ? 'Plain text is shown while searching so matches stay highlighted'
      : 'Render episode bodies as Markdown'}
    onclick={onToggleMarkdown}
  >
    Markdown
  </button>
  {#if !searching}
    <button
      type="button"
      class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
      onclick={onExpandAll}
    >
      Expand all
    </button>
    <button
      type="button"
      class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
      onclick={onCollapseAll}
    >
      Collapse all
    </button>
  {/if}
  <span class="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">
    {#if searching || countFilterActive}{filteredCount}/{totalCount}{/if}
    {#if currentNo}
      {#if searching || countFilterActive}<span class="text-muted-foreground/60"> · </span>{/if}
      <span class="text-muted-foreground/60">#</span>{currentNo}/{totalCount}
    {/if}
  </span>
</div>
