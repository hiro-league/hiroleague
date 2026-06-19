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
  import { collapsedEdges, connectionsForNode, hasMatch } from './graph-detail-helpers';
  import GraphDetailConnectionsTab from './detail/GraphDetailConnectionsTab.svelte';
  import GraphDetailEpisodesTab from './detail/GraphDetailEpisodesTab.svelte';
  import GraphDetailHighlight from './detail/GraphDetailHighlight.svelte';

  type AggregateSelection = {
    id: string;
    source: string;
    target: string;
    collapsedIds: string[];
    whole?: boolean;
  };
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
    onNavigate: (sel: { kind: 'node' | 'edge'; id: string }) => void;
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

  const SUMMARY_SNIPPET_CHARS = 240;

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
  const summaryText = $derived(node ? node.summary : edge ? (edge.fact ?? '') : '');

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

  function toggleChunk(id: string): void {
    const next = new Set(expandedChunks);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    expandedChunks = next;
  }

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

  $effect(() => {
    selectionKey;
    tab = 'episodes';
    search = '';
    summaryExpanded = false;
    expandedChunks = new Set();
    onPreview(null);
  });
  $effect(() => () => onPreview(null));

  let chunkAbort: AbortController | null = null;
  $effect(() => {
    const ids = selectedChunkIds;
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
          {#if edge}“{/if}<GraphDetailHighlight text={shown} {search} />{#if edge}”{/if}
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

    <div class="flex flex-1 flex-col gap-2 overflow-auto p-3">
      {#if tab === 'episodes'}
        <GraphDetailEpisodesTab
          {edge}
          {search}
          {selectedChunkIds}
          {selectedDocCount}
          {chunksLoading}
          {chunkDetails}
          {matchedChunkCount}
          {chunkGroups}
          {expandedChunks}
          onToggleChunk={toggleChunk}
        />
      {:else}
        <GraphDetailConnectionsTab
          {search}
          {connections}
          {filteredConnections}
          {onNavigate}
          {onPreview}
        />
      {/if}
    </div>
  </aside>
{/if}
