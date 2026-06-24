<script lang="ts">
  import { CalendarDays, FileText } from '@lucide/svelte';
  import type { GraphChunkDetail, GraphEdgeDTO } from '$lib/api/knowledge';
  import Highlight from '$lib/search/Highlight.svelte';

  let {
    edge,
    search,
    selectedChunkIds,
    selectedDocCount,
    chunksLoading,
    chunkDetails,
    matchedChunkCount,
    chunkGroups,
    expandedChunks,
    onToggleChunk
  }: {
    edge: GraphEdgeDTO | null;
    search: string;
    selectedChunkIds: string[];
    selectedDocCount: number;
    chunksLoading: boolean;
    chunkDetails: GraphChunkDetail[];
    matchedChunkCount: number;
    chunkGroups: { title: string; chunks: GraphChunkDetail[] }[];
    expandedChunks: Set<string>;
    onToggleChunk: (id: string) => void;
  } = $props();

  const CHUNK_SNIPPET_CHARS = 220;

  const chunkDateFmt = new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });

  function formatChunkDate(iso: string | null): { label: string; title: string } | null {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return { label: chunkDateFmt.format(d), title: d.toLocaleString() };
  }
</script>

{#if edge && (edge.valid_at || edge.invalid_at || edge.expired_at)}
  {@const validFrom = formatChunkDate(edge.valid_at)}
  {@const validUntil = formatChunkDate(edge.invalid_at)}
  {@const retired = formatChunkDate(edge.expired_at)}
  <div class="flex flex-col gap-1 rounded-md border bg-muted/30 p-2">
    <span class="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
      <CalendarDays size={11} aria-hidden="true" /> Validity
    </span>
    <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-foreground/80">
      <span title={validFrom?.title}>From: {validFrom ? validFrom.label : '—'}</span>
      {#if validUntil}<span title={validUntil.title}>Until: {validUntil.label}</span>{/if}
      {#if retired}
        <span class="text-amber-500" title={`Superseded · ${retired.title}`}>Retired: {retired.label}</span>
      {/if}
    </div>
  </div>
{/if}

<div class="mt-1 flex items-center justify-between">
  <span class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Sources</span>
  <span class="text-[11px] text-muted-foreground">
    {search.trim() ? `${matchedChunkCount}/${selectedChunkIds.length}` : selectedChunkIds.length}
    episode{selectedChunkIds.length === 1 ? '' : 's'}{selectedDocCount
      ? ` · ${selectedDocCount} doc${selectedDocCount === 1 ? '' : 's'}`
      : ''}
  </span>
</div>

{#if selectedChunkIds.length === 0}
  <p class="text-xs text-muted-foreground">
    No source episodes — this entity has no edge-borne provenance (isolated node).
  </p>
{:else if chunksLoading}
  <p class="text-xs text-muted-foreground">Loading episode text…</p>
{:else if chunkDetails.length === 0}
  <p class="text-xs text-muted-foreground">Episode text unavailable (the source may have been removed).</p>
{:else if matchedChunkCount === 0}
  <p class="text-xs text-muted-foreground">No episodes match “{search.trim()}”.</p>
{:else}
  <div class="space-y-3">
    {#each chunkGroups as group (group.title)}
      <div>
        <div class="mb-1 flex items-center gap-1.5 text-xs font-medium">
          <FileText size={13} class="flex-none text-muted-foreground" aria-hidden="true" />
          <span class="truncate" title={group.title}>{group.title}</span>
        </div>
        <div class="space-y-1.5">
          {#each group.chunks as c (c.id)}
            {@const expanded = expandedChunks.has(c.id)}
            {@const long = c.text.length > CHUNK_SNIPPET_CHARS}
            {@const date = formatChunkDate(c.valid_at)}
            {@const body = expanded || !long ? c.text : c.text.slice(0, CHUNK_SNIPPET_CHARS) + '…'}
            <div class="rounded-md border bg-muted/40 p-2 text-xs">
              {#if c.heading_path || date}
                <div class="mb-0.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                  <span class="min-w-0 flex-1 truncate" title={c.heading_path ?? ''}>{c.heading_path ?? ''}</span>
                  {#if date}
                    <span class="flex flex-none items-center gap-1 tabular-nums" title={`Event date · ${date.title}`}>
                      <CalendarDays size={10} aria-hidden="true" />
                      {date.label}
                    </span>
                  {/if}
                </div>
              {/if}
              <p class="whitespace-pre-wrap break-words text-foreground/90">
                <Highlight text={body} query={search} />
              </p>
              {#if long}
                <button
                  type="button"
                  onclick={() => onToggleChunk(c.id)}
                  class="mt-1 text-[11px] font-medium text-primary hover:underline"
                >
                  {expanded ? 'Show less' : 'Show more'}
                </button>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    {/each}
  </div>
{/if}
