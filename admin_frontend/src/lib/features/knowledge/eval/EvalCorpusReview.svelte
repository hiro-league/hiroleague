<!--
  Reusable corpus transcript with search + match highlight.

  Renders the memory-eval corpus episodes as a dated transcript, with a search box that filters to
  matching episodes and highlights the term in the body. Used in two places:
    1. The Eval panel's "Corpus" section (review the turns the questions probe).
    2. A "Corpus" tab inside the retrieval/ingest trace dialogs (cross-reference a recalled/
       ingested fact against its source episode while inspecting the pipeline).
-->
<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import type { EvalEpisode } from '$lib/api/knowledge';
  import { highlightSegments } from '$lib/features/knowledge/eval/eval-highlight';

  let {
    episodes,
    /** Compact = denser padding + smaller max-height, for the trace-dialog tab. */
    compact = false,
    /** Search term — bindable so a parent can own the input (e.g. the panel's Corpus header). */
    search = $bindable(''),
    /** Render the built-in search bar. Off when the parent supplies its own input. */
    showSearch = true
  }: { episodes: EvalEpisode[]; compact?: boolean; search?: string; showSearch?: boolean } =
    $props();

  const filtered = $derived.by(() => {
    const term = search.trim().toLowerCase();
    if (!term) return episodes;
    return episodes.filter((ep) => `${ep.body} ${ep.speaker} ${ep.id}`.toLowerCase().includes(term));
  });

  // Episode timestamps are dated turns; show the date only (time-of-day is noise here).
  function fmtDate(iso: string): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().slice(0, 10);
  }
</script>

<div class="grid gap-2">
  {#if showSearch}
    <div class="flex flex-wrap items-center gap-2">
      <input
        class="h-7 w-56 rounded-md border bg-background px-2 font-sans text-xs"
        placeholder="Search episodes…"
        bind:value={search}
      />
      {#if search.trim()}
        <span class="font-sans text-xs text-muted-foreground">
          {filtered.length} of {episodes.length} match
        </span>
        <button
          type="button"
          class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
          onclick={() => (search = '')}
        >
          Clear
        </button>
      {/if}
    </div>
  {/if}
  <div class="overflow-y-auto rounded-md border {compact ? 'max-h-[60vh]' : 'max-h-96'}">
    {#if filtered.length === 0}
      <p class="px-3 py-2 font-sans text-xs text-muted-foreground">No episodes match “{search}”.</p>
    {:else}
      {#each filtered as ep (ep.id)}
        <div class="border-t {compact ? 'px-3 py-1.5' : 'px-3 py-2'} first:border-t-0">
          <div class="flex flex-wrap items-center gap-2 font-sans text-[11px] text-muted-foreground">
            <span class="font-mono">{ep.id}</span>
            <span class="font-mono tabular-nums">{fmtDate(ep.timestamp)}</span>
            {#if ep.speaker}<Badge variant="outline" class="font-sans normal-case">{ep.speaker}</Badge>{/if}
          </div>
          <p class="mt-1 whitespace-pre-wrap font-sans text-sm leading-6">{#each highlightSegments(ep.body, search) as seg}{#if seg.hit}<mark class="rounded bg-amber-200 text-inherit dark:bg-amber-500/40">{seg.text}</mark>{:else}{seg.text}{/if}{/each}</p>
        </div>
      {/each}
    {/if}
  </div>
</div>
