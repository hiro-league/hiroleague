<script lang="ts">
  /**
   * Selection / provenance detail panel for the knowledge graph view (the right-hand aside
   * shown when an entity, relation, or "N other relations" aggregate edge is selected).
   *
   * Layout: header (icon/type/name) → a persistent SUMMARY + SEARCH area → two sub-tabs:
   *  - Episodes: the real episode text (one episode = one chunk), grouped by document and
   *    lazy-fetched on selection. The search box filters this list (hide non-matches) and
   *    highlights matches in both the episodes AND the summary/fact.
   *  - Connections: what the selection links to. An ENTITY → its relations (click a relation to
   *    inspect it); a RELATION → its two entities (click to jump to one); an AGGREGATE → all the
   *    relations it folds. Each row is icon-tagged (relation vs entity) and labelled by what it
   *    selects, so clicking is never a surprise. The same search filters/highlights this list too.
   *
   * Clicking a connection re-selects it via onNavigate, which also slides the camera to centre it.
   * The chunk-detail request is AbortController-guarded (cancelled on selection change / unmount).
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
    Search,
    Spline,
    User,
    X
  } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import {
    fetchGraphChunksDetail,
    type GraphChunkDetail,
    type GraphEdgeDTO,
    type GraphNodeDTO
  } from '$lib/api/knowledge';
  import type { KnowledgeGraphModel } from '../state/knowledge-graph.svelte';
  import { colorFor, humanizeRelType } from './knowledge-graph-style';
  import {
    collapsedEdges,
    connectionsForNode,
    hasMatch,
    highlightParts
  } from './graph-detail-helpers';

  /** The selected aggregate edge (synthetic; not a real GraphEdgeDTO). `whole` = it folds the entire
   *  pair ("X relations") vs the leftover ("N other relations"). */
  type AggregateSelection = {
    id: string;
    source: string;
    target: string;
    collapsedIds: string[];
    whole?: boolean;
  };
  /** One Connections row: navKind/navId say what clicking selects; entityType drives the icon. */
  type ConnRow = {
    navKind: 'node' | 'edge';
    navId: string;
    title: string;
    subtitle: string;
    invalid: boolean;
    entityType: string | null;
  };

  interface Props {
    node: GraphNodeDTO | null;
    edge: GraphEdgeDTO | null;
    aggregateEdge: AggregateSelection | null;
    graph: KnowledgeGraphModel;
    side: 'left' | 'right';
    onFlipSide: () => void;
    /** Select a connection AND slide the camera to centre it (handled by the parent). */
    onNavigate: (sel: { kind: 'node' | 'edge'; id: string }) => void;
    /** Transiently highlight a connection on the canvas while it's hovered (null = clear). */
    onPreview: (sel: { kind: 'node' | 'edge'; id: string } | null) => void;
  }
  let { node, edge, aggregateEdge, graph, side, onFlipSide, onNavigate, onPreview }: Props =
    $props();

  const NODE_TYPE_ICON: Record<string, typeof Circle> = {
    Person: User,
    Place: MapPin,
    Event: CalendarDays,
    Organization: Building2,
    Object: Package,
    Entity: Circle
  };
  const nodeIcon = (type: string | null): typeof Circle => NODE_TYPE_ICON[type ?? 'Entity'] ?? Circle;

  const CHUNK_SNIPPET_CHARS = 220;
  const SUMMARY_SNIPPET_CHARS = 240;

  // ── Local UI state (reset whenever the selection changes) ──
  let tab = $state<'episodes' | 'connections'>('episodes');
  let search = $state('');
  let summaryExpanded = $state(false);
  let chunkDetails = $state<GraphChunkDetail[]>([]);
  let chunksLoading = $state(false);
  let expandedChunks = $state<Set<string>>(new Set());

  const selectionKey = $derived(node?.id ?? edge?.id ?? aggregateEdge?.id ?? null);
  const nodeById = $derived(new Map(graph.nodes().map((n) => [n.id, n])));
  const edgeById = $derived(new Map(graph.links().map((e) => [e.id, e])));
  const aggEdges = $derived(
    aggregateEdge ? collapsedEdges(aggregateEdge.collapsedIds, edgeById) : []
  );

  const headerType = $derived(node ? node.type : aggregateEdge ? 'Relations' : 'Relation');
  const headerName = $derived(
    node
      ? node.name
      : edge
        ? humanizeRelType(edge.rel_type)
        : aggregateEdge
          ? `${aggregateEdge.collapsedIds.length} ${aggregateEdge.whole ? 'relations' : 'other relations'}`
          : ''
  );
  // The summary/fact searched + highlighted (entity summary, or edge fact). None for aggregates.
  const summaryText = $derived(node ? node.summary : edge ? (edge.fact ?? '') : '');

  // chunk_ids of the current selection (an aggregate rolls up the union of its folded edges').
  const selectedChunkIds = $derived.by<string[]>(() => {
    if (node) return node.chunk_ids;
    if (edge) return edge.chunk_ids;
    if (aggregateEdge) {
      const ids = new Set<string>();
      for (const e of aggEdges) for (const c of e.chunk_ids) ids.add(c);
      return [...ids];
    }
    return [];
  });
  const selectedDocCount = $derived(
    node ? node.document_ids.length : edge ? edge.document_ids.length : 0
  );

  // Connections rows — labelled + icon-tagged by what clicking selects (see header comment).
  const connections = $derived.by<ConnRow[]>(() => {
    if (node) {
      return connectionsForNode(node.id, graph.links()).map((c) => ({
        navKind: 'edge' as const,
        navId: c.edgeId,
        title: humanizeRelType(c.relType),
        subtitle: `${c.outgoing ? '→' : '←'} ${graph.nodeName(c.neighborId)}`,
        invalid: c.invalid,
        entityType: null
      }));
    }
    if (edge) {
      return [edge.source, edge.target].map((id, i) => ({
        navKind: 'node' as const,
        navId: id,
        title: graph.nodeName(id),
        subtitle: i === 0 ? 'Source' : 'Target',
        invalid: false,
        entityType: nodeById.get(id)?.type ?? 'Entity'
      }));
    }
    if (aggregateEdge) {
      return aggEdges.map((e) => ({
        navKind: 'edge' as const,
        navId: e.id,
        title: humanizeRelType(e.rel_type),
        subtitle: e.fact,
        invalid: e.invalid_at != null || e.expired_at != null,
        entityType: null
      }));
    }
    return [];
  });
  const filteredConnections = $derived(
    search.trim()
      ? connections.filter((c) => hasMatch(c.title, search) || hasMatch(c.subtitle, search))
      : connections
  );

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

  function toggleChunk(id: string): void {
    const next = new Set(expandedChunks);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    expandedChunks = next;
  }

  // Episodes grouped by document, applying the search FILTER (hide non-matching episode text).
  const chunkGroups = $derived.by(() => {
    const groups = new Map<string, GraphChunkDetail[]>();
    for (const c of chunkDetails) {
      if (search.trim() && !hasMatch(c.text, search)) continue;
      const title = c.document_title || c.document_id || 'Unknown document';
      const list = groups.get(title);
      if (list) list.push(c);
      else groups.set(title, [c]);
    }
    return [...groups.entries()].map(([title, chunks]) => ({ title, chunks }));
  });
  const matchedChunkCount = $derived(chunkGroups.reduce((n, g) => n + g.chunks.length, 0));
  const summaryShowFull = $derived(
    summaryExpanded || (search.trim().length > 0 && hasMatch(summaryText, search))
  );

  // Reset local UI when the selection changes (and clear any lingering hover preview).
  $effect(() => {
    selectionKey; // tracked
    tab = 'episodes';
    search = '';
    summaryExpanded = false;
    expandedChunks = new Set();
    onPreview(null);
  });
  // Clear the canvas hover-preview when the panel unmounts.
  $effect(() => () => onPreview(null));

  let chunkAbort: AbortController | null = null;
  $effect(() => {
    const ids = selectedChunkIds; // tracked
    chunkAbort?.abort();
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
    void (async () => {
      try {
        const res = await fetchGraphChunksDetail(ids, ctrl.signal);
        if (ctrl.signal.aborted) return;
        chunkDetails = res.data?.chunks ?? [];
      } catch (err) {
        if (ctrl.signal.aborted) return;
        console.error('graph episode-detail lookup failed', err);
        chunkDetails = [];
      } finally {
        if (!ctrl.signal.aborted) chunksLoading = false;
      }
    })();
    return () => ctrl.abort();
  });
</script>

{#if node || edge || aggregateEdge}
  {@const accent = node ? colorFor(node.type) : 'rgb(100,116,139)'}
  {@const HeaderIcon = node ? nodeIcon(node.type) : Spline}
  <aside
    class={cn(
      'absolute top-0 flex h-full w-80 flex-col overflow-hidden bg-background/80 text-sm shadow-lg backdrop-blur',
      side === 'left' ? 'left-0 border-r' : 'right-0 border-l'
    )}
  >
    <!-- header -->
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
          {headerType}
        </div>
        <div class="truncate font-semibold" title={headerName}>{headerName}</div>
      </div>
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

    <!-- persistent summary + search (above the sub-tabs; searches BOTH tabs) -->
    <div class="flex flex-none flex-col gap-2 border-b p-3">
      <div class="relative">
        <Search
          size={13}
          class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <input
          type="search"
          bind:value={search}
          placeholder="Search episodes &amp; connections…"
          aria-label="Search episode text, summary and connections"
          class="h-7 w-full rounded-md border bg-background pl-7 pr-7 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-search-cancel-button]:hidden"
        />
        {#if search}
          <button
            type="button"
            onclick={() => (search = '')}
            class="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Clear search"
            title="Clear search"
          >
            <X size={13} aria-hidden="true" />
          </button>
        {/if}
      </div>

      {#if node && node.aliases.length}
        <div class="text-xs">
          <span class="text-muted-foreground">aliases:</span> {node.aliases.join(', ')}
        </div>
      {/if}

      {#if summaryText}
        {@const long = summaryText.length > SUMMARY_SNIPPET_CHARS}
        {@const shown =
          summaryShowFull || !long ? summaryText : summaryText.slice(0, SUMMARY_SNIPPET_CHARS) + '…'}
        <div class={cn('rounded-md bg-muted/40 p-2 text-xs text-muted-foreground', edge && 'italic')}>
          {#if edge}“{/if}{@render hl(shown)}{#if edge}”{/if}
          {#if long}
            <button
              type="button"
              onclick={() => (summaryExpanded = !summaryShowFull)}
              class="ml-1 font-medium text-primary not-italic hover:underline"
            >
              {summaryShowFull ? 'Show less' : 'Show more'}
            </button>
          {/if}
        </div>
      {:else if aggregateEdge}
        <div class="text-xs text-muted-foreground">
          {graph.nodeName(aggregateEdge.source)} ↔ {graph.nodeName(aggregateEdge.target)}
        </div>
      {/if}
    </div>

    <!-- sub-tab strip -->
    <div class="flex flex-none gap-1 border-b px-2 pt-2" role="tablist">
      <button
        type="button"
        role="tab"
        aria-selected={tab === 'episodes'}
        onclick={() => (tab = 'episodes')}
        class={cn(
          'rounded-t-md px-2.5 py-1 text-xs font-medium transition-colors',
          tab === 'episodes'
            ? 'border-b-2 border-primary text-foreground'
            : 'text-muted-foreground hover:text-foreground'
        )}
      >
        Episodes <span class="tabular-nums opacity-70">{selectedChunkIds.length}</span>
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={tab === 'connections'}
        onclick={() => (tab = 'connections')}
        class={cn(
          'rounded-t-md px-2.5 py-1 text-xs font-medium transition-colors',
          tab === 'connections'
            ? 'border-b-2 border-primary text-foreground'
            : 'text-muted-foreground hover:text-foreground'
        )}
      >
        Connections <span class="tabular-nums opacity-70">{connections.length}</span>
      </button>
    </div>

    <!-- body -->
    <div class="flex flex-1 flex-col gap-2 overflow-auto p-3">
      {#if tab === 'episodes'}
        {#if edge && (edge.valid_at || edge.invalid_at || edge.expired_at)}
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
                <span class="text-amber-500" title={`Superseded · ${retired.title}`}
                  >Retired: {retired.label}</span
                >
              {/if}
            </div>
          </div>
        {/if}

        <div class="mt-1 flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
            >Sources</span
          >
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
          <p class="text-xs text-muted-foreground">
            Episode text unavailable (the source may have been removed).
          </p>
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
                      <p class="whitespace-pre-wrap break-words text-foreground/90">{@render hl(body)}</p>
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
      {:else}
        <!-- Connections -->
        {#if connections.length === 0}
          <p class="text-xs text-muted-foreground">No connections.</p>
        {:else if filteredConnections.length === 0}
          <p class="text-xs text-muted-foreground">No connections match “{search.trim()}”.</p>
        {:else}
          <div class="space-y-1">
            {#each filteredConnections as c (c.navId)}
              {@render connRow(c)}
            {/each}
          </div>
        {/if}
      {/if}
    </div>
  </aside>
{/if}

<!-- Highlight a run of text for the active search term (no {@html}; real text nodes). -->
{#snippet hl(text: string)}{#each highlightParts(text, search) as part}{#if part.match}<mark
        class="rounded-sm bg-amber-300/60 text-foreground dark:bg-amber-500/40">{part.text}</mark
      >{:else}{part.text}{/if}{/each}{/snippet}

<!-- One clickable Connections row: icon (relation vs entity) + title + subtitle. -->
{#snippet connRow(c: ConnRow)}
  {@const RowIcon = c.navKind === 'edge' ? Spline : nodeIcon(c.entityType)}
  <button
    type="button"
    onclick={() => {
      onPreview(null);
      onNavigate({ kind: c.navKind, id: c.navId });
    }}
    onmouseenter={() => onPreview({ kind: c.navKind, id: c.navId })}
    onmouseleave={() => onPreview(null)}
    onfocus={() => onPreview({ kind: c.navKind, id: c.navId })}
    onblur={() => onPreview(null)}
    class="flex w-full items-start gap-2 rounded-md border bg-muted/30 px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent"
  >
    <RowIcon size={13} class="mt-0.5 flex-none text-muted-foreground" aria-hidden="true" />
    <div class="min-w-0 flex-1">
      <div class={cn('truncate font-medium', c.invalid && 'text-muted-foreground line-through')} title={c.title}>
        {@render hl(c.title)}
      </div>
      {#if c.subtitle}
        <div class="truncate text-[11px] text-muted-foreground" title={c.subtitle}>{@render hl(c.subtitle)}</div>
      {/if}
    </div>
  </button>
{/snippet}
