<script lang="ts">
  /**
   * Selection / provenance detail panel for the knowledge graph view (the right-hand
   * aside shown when a node or edge is selected). Self-contained: it owns its own lazy
   * chunk-detail fetch (the DTO carries only chunk_ids, so the real chunk text + owning
   * document titles are fetched on selection), grouped by document for display.
   *
   * The request is AbortController-guarded (cancelled on selection change / unmount) — a
   * leaked same-origin request matters because pages + API share one origin and the
   * browser caps ~6 connections per origin.
   */
  import {
    Building2,
    CalendarDays,
    Circle,
    FileText,
    MapPin,
    Package,
    PanelLeft,
    PanelRight,
    Spline,
    User
  } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import {
    fetchGraphChunksDetail,
    type GraphChunkDetail,
    type GraphEdgeDTO,
    type GraphNodeDTO
  } from '$lib/api/knowledge';
  import type { KnowledgeGraphModel } from '../state/knowledge-graph.svelte';
  import { colorFor } from './knowledge-graph-style';

  interface Props {
    node: GraphNodeDTO | null;
    edge: GraphEdgeDTO | null;
    /** Model — used for nodeName (edge endpoints) + clearSelection (close button). */
    graph: KnowledgeGraphModel;
    /** Which edge of the canvas this aside docks against. */
    side: 'left' | 'right';
    /** Flip the aside to the other side (pins an explicit left/right preference). */
    onFlipSide: () => void;
  }
  let { node, edge, graph, side, onFlipSide }: Props = $props();

  // Map entity type → a Lucide icon (mirrors the canvas disc icons); relations use Spline.
  const NODE_TYPE_ICON: Record<string, typeof Circle> = {
    Person: User,
    Place: MapPin,
    Event: CalendarDays,
    Organization: Building2,
    Object: Package,
    Entity: Circle
  };
  const nodeIcon = (type: string): typeof Circle => NODE_TYPE_ICON[type] ?? Circle;

  const CHUNK_SNIPPET_CHARS = 220;
  let chunkDetails = $state<GraphChunkDetail[]>([]);
  let chunksLoading = $state(false);
  let expandedChunks = $state<Set<string>>(new Set());

  // Chunk event date (episode `valid_at`): the semantic "when this happened" time, not the
  // ingest time. Shown as an absolute date on each chunk card (full timestamp on hover).
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

  // chunk_ids of the current selection (node provenance is rolled up from its edges).
  const selectedChunkIds = $derived(node ? node.chunk_ids : edge ? edge.chunk_ids : []);
  const selectedDocCount = $derived(
    node ? node.document_ids.length : edge ? edge.document_ids.length : 0
  );

  function toggleChunk(id: string): void {
    const next = new Set(expandedChunks);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    expandedChunks = next;
  }

  // Group fetched chunks by their document title for a "document → chunks" layout.
  const chunkGroups = $derived.by(() => {
    const groups = new Map<string, GraphChunkDetail[]>();
    for (const c of chunkDetails) {
      const title = c.document_title || c.document_id || 'Unknown document';
      const list = groups.get(title);
      if (list) list.push(c);
      else groups.set(title, [c]);
    }
    return [...groups.entries()].map(([title, chunks]) => ({ title, chunks }));
  });

  // In-flight chunk-detail request; aborted when the selection changes or the
  // panel unmounts so we never leak/queue same-origin connections (a leaked
  // request blocks the packaged admin UI — pages + API share one origin and the
  // browser caps ~6 connections per origin).
  let chunkAbort: AbortController | null = null;

  // Fetch chunk text whenever the selection (and thus its chunk_ids) changes.
  $effect(() => {
    const ids = selectedChunkIds; // tracked
    expandedChunks = new Set();
    chunkAbort?.abort(); // cancel a previous selection's still-pending lookup
    chunkAbort = null;
    if (ids.length === 0) {
      chunkDetails = [];
      chunksLoading = false;
      return;
    }
    const ctrl = new AbortController();
    chunkAbort = ctrl;
    chunkDetails = [];
    chunksLoading = true;
    // apiRequest THROWS on error/timeout/abort — must catch, or chunksLoading
    // sticks on "Loading…" forever and the rejection goes unhandled.
    void (async () => {
      try {
        const res = await fetchGraphChunksDetail(ids, ctrl.signal);
        if (ctrl.signal.aborted) return;
        chunkDetails = res.data?.chunks ?? [];
      } catch (err) {
        if (ctrl.signal.aborted) return; // expected on selection change / unmount
        console.error('graph chunk-detail lookup failed', err);
        chunkDetails = []; // panel falls back to "chunk text unavailable"
      } finally {
        if (!ctrl.signal.aborted) chunksLoading = false;
      }
    })();
    return () => ctrl.abort();
  });
</script>

{#if node || edge}
  {@const isNode = !!node}
  {@const accent = node ? colorFor(node.type) : 'rgb(100,116,139)'}
  {@const HeaderIcon = node ? nodeIcon(node.type) : Spline}
  <aside
    class={cn(
      'absolute top-0 flex h-full w-80 flex-col overflow-hidden bg-background/80 text-sm shadow-lg backdrop-blur',
      side === 'left' ? 'left-0 border-r' : 'right-0 border-l'
    )}
  >
    <!-- header: entity/relation icon + type + name, tinted by type colour -->
    <div
      class="flex items-start gap-2.5 border-b p-3"
      style="background-color: color-mix(in srgb, {accent} 14%, transparent);"
    >
      <span
        class="mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-md text-white"
        style="background-color: {accent};"
      >
        <HeaderIcon size={16} aria-hidden="true" />
      </span>
      <div class="min-w-0 flex-1">
        <div class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {isNode ? node?.type : 'Relation'}
        </div>
        <div class="truncate font-semibold" title={isNode ? node?.name : edge?.rel_type}>
          {isNode ? node?.name : edge?.rel_type}
        </div>
      </div>
      <!-- Flip the aside to the other side. Icon points the way it will move. -->
      <button
        type="button"
        onclick={onFlipSide}
        class="rounded px-1 text-muted-foreground hover:bg-accent"
        aria-label={side === 'left' ? 'Move panel to the right' : 'Move panel to the left'}
        title={side === 'left' ? 'Move panel right' : 'Move panel left'}
      >
        {#if side === 'left'}
          <PanelRight size={15} aria-hidden="true" />
        {:else}
          <PanelLeft size={15} aria-hidden="true" />
        {/if}
      </button>
      <button
        type="button"
        onclick={() => graph.clearSelection()}
        class="-mr-1 rounded px-1.5 text-muted-foreground hover:bg-accent"
        aria-label="Close details">✕</button
      >
    </div>

    <!-- body -->
    <div class="flex flex-1 flex-col gap-2 overflow-auto p-3">
      {#if node}
        {#if node.aliases.length}
          <div class="text-xs">
            <span class="text-muted-foreground">aliases:</span> {node.aliases.join(', ')}
          </div>
        {/if}
        <!-- #5: Graphiti's generated entity summary (already on the DTO). -->
        {#if node.summary}
          <div class="rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
            {node.summary}
          </div>
        {/if}
      {:else if edge}
        <div class="text-muted-foreground">
          {graph.nodeName(edge.source)} → {graph.nodeName(edge.target)}
        </div>
        {#if edge.fact}
          <div class="rounded-md bg-muted/40 p-2 text-xs italic">“{edge.fact}”</div>
        {/if}
        <!-- Temporal validity of the FACT (Graphiti edge), not of the chunks: valid_at =
             when it became true · invalid_at = when it stopped · expired_at = when the system
             learned it was superseded (a retired fact). Chunks themselves only carry an event
             date (shown per-chunk below). Only rendered when at least one date is present. -->
        {#if edge.valid_at || edge.invalid_at || edge.expired_at}
          {@const validFrom = formatChunkDate(edge.valid_at)}
          {@const validUntil = formatChunkDate(edge.invalid_at)}
          {@const retired = formatChunkDate(edge.expired_at)}
          <div class="flex flex-col gap-1 rounded-md border bg-muted/30 p-2">
            <span
              class="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground"
            >
              <CalendarDays size={11} aria-hidden="true" /> Validity
            </span>
            <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-foreground/80">
              <span title={validFrom?.title}>From: {validFrom ? validFrom.label : '—'}</span>
              {#if validUntil}<span title={validUntil.title}>Until: {validUntil.label}</span>{/if}
              {#if retired}
                <span class="text-amber-500" title={`Superseded · ${retired.title}`}>
                  Retired: {retired.label}
                </span>
              {/if}
            </div>
          </div>
        {/if}
      {/if}

      <!-- sources: real chunk text grouped by document (lazy-fetched on select) -->
      <div class="mt-1 flex items-center justify-between">
        <span class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
          >Sources</span
        >
        <span class="text-[11px] text-muted-foreground">
          {selectedChunkIds.length} chunk{selectedChunkIds.length === 1 ? '' : 's'} ·
          {selectedDocCount} doc{selectedDocCount === 1 ? '' : 's'}
        </span>
      </div>

      {#if selectedChunkIds.length === 0}
        <p class="text-xs text-muted-foreground">
          No source chunks — this entity has no edge-borne provenance (isolated node).
        </p>
      {:else if chunksLoading}
        <p class="text-xs text-muted-foreground">Loading chunk text…</p>
      {:else if chunkDetails.length === 0}
        <p class="text-xs text-muted-foreground">
          Chunk text unavailable (the source document may have been removed).
        </p>
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
                  <div class="rounded-md border bg-muted/40 p-2 text-xs">
                    <!-- heading path (left, truncates) + event date (right, valid_at). -->
                    {#if c.heading_path || date}
                      <div
                        class="mb-0.5 flex items-center gap-2 text-[10px] text-muted-foreground"
                      >
                        <span class="min-w-0 flex-1 truncate" title={c.heading_path ?? ''}>
                          {c.heading_path ?? ''}
                        </span>
                        {#if date}
                          <span
                            class="flex flex-none items-center gap-1 tabular-nums"
                            title={`Event date · ${date.title}`}
                          >
                            <CalendarDays size={10} aria-hidden="true" />
                            {date.label}
                          </span>
                        {/if}
                      </div>
                    {/if}
                    <p class="whitespace-pre-wrap break-words text-foreground/90">
                      {expanded || !long ? c.text : c.text.slice(0, CHUNK_SNIPPET_CHARS) + '…'}
                    </p>
                    {#if long}
                      <button
                        type="button"
                        onclick={() => toggleChunk(c.id)}
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
    </div>
  </aside>
{/if}
