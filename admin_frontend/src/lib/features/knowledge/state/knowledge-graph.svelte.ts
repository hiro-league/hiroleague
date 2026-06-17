/**
 * Knowledge Graph tab controller (graph viz MVP).
 *
 * Holds the in-memory graph (nodes/edges) for the force-directed view and
 * applies live `knowledge.graph.*` SSE deltas. The EventSource lifecycle is
 * owned by KnowledgeGraphPanel (connect on mount, disconnect on destroy) so it
 * only runs while the Graph tab is open.
 *
 * Strategy (see docs/knowledge-graph-viz-design.md):
 *  - initial paint = one full export
 *  - live upserts = incremental deltas, coalesced per animation frame so a fast
 *    ingest doesn't thrash the force simulation
 *  - `ingest_completed` = one debounced reconciling re-export (heals drops)
 *
 * Node/edge objects are mutated in place on upsert (not replaced) so force-graph
 * preserves their simulated x/y positions across "pulse" (provenance-merge) updates.
 */

import {
  exportKnowledgeGraph,
  listKnowledgeGraphEpisodes,
  listKnowledgeGraphGroups,
  searchGraphChunks,
  type GraphEdgeDTO,
  type GraphEdgeEvent,
  type GraphEpisode,
  type GraphGroup,
  type GraphIngestProgress,
  type GraphNodeDTO,
  type GraphNodeEvent
} from '$lib/api/knowledge';
import { getPreferences } from '$lib/api/preferences';
import { connectKnowledgeGraphEvents } from '../shared/knowledge-events';
import { GLOW_MS } from '../graph/engine/graph-config';
import { linkEndId } from '../graph/engine/graph-types';
import { KNOWN_NODE_TYPE_ORDER } from '../graph/knowledge-graph-style';
import { PREF_KEYS } from '$lib/preferences/keys';
import {
  readLocalString,
  readSessionString,
  removeSessionString,
  writeLocalString,
  writeSessionString
} from '$lib/preferences/storage';

export interface KnowledgeGraphModelDeps {
  setError: (msg: string | null) => void;
}

export type GraphSelection = { kind: 'node'; id: string } | { kind: 'edge'; id: string } | null;

/** One row of the edge-type filter strip: a type, how many carry it, hidden state. */
export type GraphTypeFacet = { type: string; count: number; hidden: boolean };

/** One node-type group for the per-type instance filter: every instance of the type plus which
 *  ones are currently visible (checked). Nodes are filtered per-INSTANCE now (pick all/none/some
 *  Persons), not per whole type — each group drives one MultiSelectFilter dropdown. */
export type GraphNodeInstanceOption = {
  id: string;
  name: string;
  connections: number; // edge degree (how many facts touch this node)
};

export type GraphNodeTypeGroup = {
  type: string;
  count: number; // total instances of this type
  visibleCount: number; // currently-visible (checked) instances
  options: GraphNodeInstanceOption[]; // all instances (component owns sort order)
  selectedIds: string[]; // visible instance ids (the dropdown's checked set)
};

// Fallback large-type warning threshold until the admin preference (graph.view.large_type_threshold)
// loads. A node type with more instances than this flags a "use search" perf note in its dropdown.
const DEFAULT_LARGE_TYPE_THRESHOLD = 200;

// ── Edge filters (the Graph options panel's "Filters" section) ──────────────────────────────
/** Edge validity filter. Mirrors the codebase's "current fact" rule (graphiti_search): a fact is
 *  CURRENT/valid when invalid_at IS NULL AND expired_at IS NULL; INVALID when either is set. */
export type EdgeValidity = 'all' | 'valid' | 'invalid';
/** Which edges to keep when an edge cap kicks in — newest or oldest by valid_at. Shared by BOTH
 *  the per-node connection cap AND the per-pair "Visible edges" collapse (one control, two uses). */
export type MaxConnBy = 'newest' | 'oldest';
/** Denoise treatment for sparse (low-connection) nodes. 'dim' fades them (render-only, no relayout),
 *  'hide' drops them (structural). Whether ANY node is sparse is governed by lowConnThreshold
 *  (0 = off) — a node is sparse when its VISIBLE degree (after edge filters) is below the threshold. */
export type LowConnTreatment = 'dim' | 'hide';
/** Denoise threshold floor. 0 = off (nothing is sparse). The slider's MAX is data-driven (the
 *  current graph's busiest node), so the range always reflects the real connection counts. */
export const LOW_CONN_THRESHOLD_MIN = 0;
export const LOW_CONN_THRESHOLD_DEFAULT = 0;
/** Inclusive epoch-ms range for a date slider; null = inactive (full span, no filtering). */
export type DateRange = { lo: number; hi: number } | null;

/** Max-connections-per-node slider cap; this value === "show all" (no cap). */
export const MAX_CONN_PER_NODE_CAP = 25;

/** "Max visible edges between nodes" per entity pair — slider bounds. The MAX value === "show all"
 *  (no aggregation). The MIN is 1: at 1 a multi-edge pair collapses ENTIRELY into one "X relations"
 *  aggregate (X = the real relation count between the two nodes); at 2+ one or more real edges show
 *  alongside an "N other relations" aggregate. A fixed 100 max avoids computing the true per-graph
 *  maximum (per design). */
export const VISIBLE_EDGES_CAP = 100;
export const VISIBLE_EDGES_MIN = 1;

/** Persisted edge-filter MODES (NOT the date ranges — those default to the data's full span). */
type EdgeFilterModes = {
  edgeValidity: EdgeValidity;
  includeUndatedEdges: boolean;
  maxConnPerNode: number;
  maxConnBy: MaxConnBy;
  visibleEdgesPerPair: number;
  lowConnTreatment: LowConnTreatment;
  lowConnThreshold: number;
};
const EDGE_FILTER_DEFAULTS: EdgeFilterModes = {
  edgeValidity: 'all',
  includeUndatedEdges: true,
  maxConnPerNode: MAX_CONN_PER_NODE_CAP, // === cap → no limit
  maxConnBy: 'newest',
  visibleEdgesPerPair: VISIBLE_EDGES_CAP, // === cap → no aggregation
  lowConnTreatment: 'dim',
  lowConnThreshold: LOW_CONN_THRESHOLD_DEFAULT // 0 = denoise off
};

function readEdgeFilterModes(): EdgeFilterModes {
  const raw = readLocalString(PREF_KEYS.knowledgeGraphEdgeFilters);
  if (!raw) return { ...EDGE_FILTER_DEFAULTS };
  try {
    const p = JSON.parse(raw) as Partial<EdgeFilterModes>;
    const cap = Number(p.maxConnPerNode);
    const vis = Number(p.visibleEdgesPerPair);
    return {
      edgeValidity: (['all', 'valid', 'invalid'] as const).includes(p.edgeValidity as EdgeValidity)
        ? (p.edgeValidity as EdgeValidity)
        : EDGE_FILTER_DEFAULTS.edgeValidity,
      includeUndatedEdges:
        typeof p.includeUndatedEdges === 'boolean'
          ? p.includeUndatedEdges
          : EDGE_FILTER_DEFAULTS.includeUndatedEdges,
      maxConnPerNode: Number.isFinite(cap)
        ? Math.min(MAX_CONN_PER_NODE_CAP, Math.max(1, Math.round(cap)))
        : EDGE_FILTER_DEFAULTS.maxConnPerNode,
      maxConnBy: p.maxConnBy === 'oldest' ? 'oldest' : 'newest',
      visibleEdgesPerPair: Number.isFinite(vis)
        ? Math.min(VISIBLE_EDGES_CAP, Math.max(VISIBLE_EDGES_MIN, Math.round(vis)))
        : EDGE_FILTER_DEFAULTS.visibleEdgesPerPair,
      lowConnTreatment: p.lowConnTreatment === 'hide' ? 'hide' : 'dim',
      lowConnThreshold: Number.isFinite(Number(p.lowConnThreshold))
        ? Math.max(LOW_CONN_THRESHOLD_MIN, Math.round(Number(p.lowConnThreshold))) // no upper clamp: data-driven
        : EDGE_FILTER_DEFAULTS.lowConnThreshold
    };
  } catch {
    return { ...EDGE_FILTER_DEFAULTS };
  }
}

/** Parse an ISO timestamp to epoch ms, or null when absent/unparseable. */
function epoch(iso: string | null): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

/** Clamp a date range to the data span; collapse to null (inactive) when it covers the full
 *  span — so a slider parked at both ends never filters (and never gates undated edges). A
 *  one-step tolerance snaps near-edge knobs to the exact span ends: the slider step-snaps its
 *  thumbs (the max rarely lands on a step boundary), which would otherwise leave `hi` a hair
 *  below the true max on mount and spuriously hide the newest edges. */
function normalizeRange(
  range: DateRange,
  span: { lo: number; hi: number } | null
): DateRange {
  if (!range || !span) return null;
  const tol = Math.max(1, (span.hi - span.lo) / 100); // == the slider's step granularity
  const lo = Math.max(span.lo, Math.min(range.lo, range.hi));
  const hi = Math.min(span.hi, Math.max(range.lo, range.hi));
  const atStart = lo <= span.lo + tol;
  const atEnd = hi >= span.hi - tol;
  if (atStart && atEnd) return null;
  return { lo: atStart ? span.lo : lo, hi: atEnd ? span.hi : hi };
}

// GLOW_MS (how long a freshly-created node/edge glows after appearing) is shared with the
// canvas engine via engine/graph-config so the recent[] prune window and the fade window agree.
// Debounce window for the post-ingest reconciling re-export (ms).
const RECONCILE_DEBOUNCE_MS = 400;
// Debounce window for the backend chunk-text search leg (ms).
const SEARCH_DEBOUNCE_MS = 250;

// Filter persistence: the hidden sets are kept in sessionStorage only — no URL params
// (filters aren't meant to be shareable links), just remembered for the session. Comma-joined;
// empty set clears the key. NODES persist hidden INSTANCE ids (per-instance filter); EDGES
// persist hidden relation TYPES.
const SESSION_HIDE_NODES = PREF_KEYS.knowledgeGraphHideNodes;
const SESSION_HIDE_EDGES = PREF_KEYS.knowledgeGraphHideEdges;
// Last-viewed partition group_id — remembered across opens (design: default = first in list,
// remember last). Restored in loadGroups() iff the group still exists.
const SESSION_ACTIVE_GROUP = PREF_KEYS.knowledgeGraphActiveGroup;
// Selected episode-filter ids, keyed by partition — sessionStorage so a refresh keeps the
// selection. Stored as a JSON map { group_id: chunk_id[] } so each partition keeps its own.
const SESSION_EPISODE_SEL = PREF_KEYS.knowledgeGraphEpisodeSel;

function readEpisodeSel(groupId: string): string[] {
  const raw = readSessionString(SESSION_EPISODE_SEL);
  if (!raw) return [];
  try {
    const map = JSON.parse(raw) as Record<string, string[]>;
    const ids = map[groupId];
    return Array.isArray(ids) ? ids.filter((s): s is string => typeof s === 'string') : [];
  } catch {
    return []; // corrupt blob → treat as no saved selection
  }
}

function writeEpisodeSel(groupId: string, ids: string[]): void {
  const raw = readSessionString(SESSION_EPISODE_SEL);
  let map: Record<string, string[]> = {};
  if (raw) {
    try {
      map = JSON.parse(raw) as Record<string, string[]>;
    } catch {
      map = {};
    }
  }
  if (ids.length > 0) map[groupId] = ids;
  else delete map[groupId];
  if (Object.keys(map).length > 0) writeSessionString(SESSION_EPISODE_SEL, JSON.stringify(map));
  else removeSessionString(SESSION_EPISODE_SEL);
}

function readHidden(key: string): Set<string> {
  const raw = readSessionString(key);
  if (!raw) return new Set();
  return new Set(raw.split(',').map((s) => s.trim()).filter(Boolean));
}

function writeHidden(key: string, hidden: Set<string>): void {
  if (hidden.size > 0) writeSessionString(key, [...hidden].join(','));
  else removeSessionString(key);
}

// Sort node-type groups: known ontology types first (in canonical order), then any
// Graphiti-emitted unknown types alphabetically.
function rankNodeType(t: string): number {
  const i = KNOWN_NODE_TYPE_ORDER.indexOf(t);
  return i === -1 ? KNOWN_NODE_TYPE_ORDER.length : i;
}

export function createKnowledgeGraphModel(deps: KnowledgeGraphModelDeps) {
  let nodes = $state<GraphNodeDTO[]>([]);
  let links = $state<GraphEdgeDTO[]>([]);
  let loading = $state(false);
  // Last load failure (timeout / network / server). Lets the panel show an actionable
  // "couldn't load — retry" warning instead of the misleading "No graph yet" empty state
  // when an export request is aborted (e.g. too many open tabs saturate the connection pool).
  let loadError = $state<string | null>(null);
  let truncated = $state(false);
  // Bumped on every full (re)export so the renderer can tell a structural reload
  // (initial load / manual reload / reconcile) apart from incremental live deltas.
  // A reload wants a fresh relayout + zoom-to-fit; live deltas should NOT re-simulate
  // and reposition the whole graph (see KnowledgeGraphPanel graphData effect).
  let loadVersion = $state(0);
  let live = $state(false);
  let progress = $state<GraphIngestProgress | null>(null);
  let selected = $state<GraphSelection>(null);
  // Group filter: the partitions present in the graph + which one is shown. We simply list
  // whatever groups exist (no privileged "knowledge is home" default) and show the selected
  // one — default = first in the list, last selection remembered (resolved in loadGroups).
  // `null` only before groups have loaded or when the graph is empty. Drives the export scope
  // and the live-event filter.
  let groups = $state<GraphGroup[]>([]);
  let activeGroupId = $state<string | null>(null);
  // id (prefixed n:/e:) -> epoch ms of last "is_new" sighting; drives the glow.
  let recent = $state<Record<string, number>>({});

  // ── View filters (client-side; the full snapshot is already in memory) ──
  // We store the HIDDEN set so the default (empty set) means "show all". Reassigned with a fresh
  // Set on every change so $state reactivity fires. Seeded from sessionStorage so a filtered view
  // is restored across opens. Nodes are filtered per-INSTANCE (hidden instance ids — pick all/none/
  // some Persons); edges per relation TYPE.
  let hiddenNodeIds = $state<Set<string>>(readHidden(SESSION_HIDE_NODES));
  let hiddenEdgeTypes = $state<Set<string>>(readHidden(SESSION_HIDE_EDGES));
  // Admin-settable threshold (graph.view.large_type_threshold) above which a node type's dropdown
  // shows a "many instances — use search" perf note. Loaded once via loadPreferences(); falls back
  // to DEFAULT_LARGE_TYPE_THRESHOLD until then.
  let largeTypeThreshold = $state(DEFAULT_LARGE_TYPE_THRESHOLD);

  // ── Edge filters (Graph options → Filters). Modes persist to localStorage; the two date
  // ranges default to the data's full span each load (absolute dates don't carry across graphs),
  // so they live as ephemeral null-until-touched state. ──
  const persistedFilters = readEdgeFilterModes();
  let edgeValidity = $state<EdgeValidity>(persistedFilters.edgeValidity);
  let includeUndatedEdges = $state(persistedFilters.includeUndatedEdges);
  let maxConnPerNode = $state(persistedFilters.maxConnPerNode);
  let maxConnBy = $state<MaxConnBy>(persistedFilters.maxConnBy);
  // Per-pair "Visible edges" cap (collapse extras into one aggregate edge); === cap → no aggregation.
  let visibleEdgesPerPair = $state(persistedFilters.visibleEdgesPerPair);
  // Denoise: dim/hide nodes with fewer than `lowConnThreshold` visible connections (0 = off).
  let lowConnTreatment = $state<LowConnTreatment>(persistedFilters.lowConnTreatment);
  let lowConnThreshold = $state(persistedFilters.lowConnThreshold);
  // null = "full span" (slider sits at both ends, no filtering); set when the user drags a knob.
  let validRange = $state<DateRange>(null);
  let creationRange = $state<DateRange>(null);

  function persistEdgeFilterModes(): void {
    writeLocalString(
      PREF_KEYS.knowledgeGraphEdgeFilters,
      JSON.stringify({
        edgeValidity,
        includeUndatedEdges,
        maxConnPerNode,
        maxConnBy,
        visibleEdgesPerPair,
        lowConnTreatment,
        lowConnThreshold
      })
    );
  }

  // Non-reactive O(1) indexes — the dedup source of truth. Values are the same
  // object references held in the reactive arrays (mutated in place on upsert).
  const nodeById = new Map<string, GraphNodeDTO>();
  const edgeById = new Map<string, GraphEdgeDTO>();

  // rAF-coalesced delta buffer.
  let pendingNodes: GraphNodeEvent[] = [];
  let pendingEdges: GraphEdgeEvent[] = [];
  let flushScheduled = false;
  let reconcileTimer: ReturnType<typeof setTimeout> | null = null;

  function rebuildArrays(): void {
    nodes = [...nodeById.values()];
    // Drop dangling edges (an edge delta can arrive before its node delta) — but FIRST
    // normalize the endpoint to its id via the shared `linkEndId`. Historically the canvas
    // fed force-graph the model's edge objects, which force-graph rewrote source/target from
    // id strings into node OBJECTS; a naive `nodeById.has(e.source)` then checked has(<object>)
    // → false → every rendered edge was filtered out, collapsing the link structure and
    // re-scattering the nodes. The engine now uses its own mirror links so the model's edges
    // keep string endpoints, but linkEndId stays as cheap insurance against either shape.
    links = [...edgeById.values()].filter(
      (e) => nodeById.has(linkEndId(e.source)) && nodeById.has(linkEndId(e.target))
    );
  }

  function upsertNode(dto: GraphNodeDTO): void {
    const existing = nodeById.get(dto.id);
    if (existing) {
      Object.assign(existing, dto); // keep reference → preserve x/y
    } else {
      nodeById.set(dto.id, { ...dto });
    }
  }

  function upsertEdge(dto: GraphEdgeDTO): void {
    const existing = edgeById.get(dto.id);
    if (existing) {
      Object.assign(existing, dto);
    } else {
      edgeById.set(dto.id, { ...dto });
    }
  }

  function flush(): void {
    flushScheduled = false;
    if (pendingNodes.length === 0 && pendingEdges.length === 0) return;
    const now = Date.now();
    const nextRecent = { ...recent };
    for (const ev of pendingNodes) {
      upsertNode(ev.node);
      if (ev.is_new) nextRecent[`n:${ev.node.id}`] = now;
    }
    for (const ev of pendingEdges) {
      upsertEdge(ev.edge);
      if (ev.is_new) nextRecent[`e:${ev.edge.id}`] = now;
    }
    pendingNodes = [];
    pendingEdges = [];
    for (const key of Object.keys(nextRecent)) {
      if (now - nextRecent[key] > GLOW_MS) delete nextRecent[key];
    }
    recent = nextRecent;
    rebuildArrays();
  }

  function scheduleFlush(): void {
    if (typeof requestAnimationFrame === 'undefined') {
      flush();
      return;
    }
    if (flushScheduled) return;
    flushScheduled = true;
    requestAnimationFrame(flush);
  }

  function scheduleReconcile(): void {
    if (reconcileTimer) clearTimeout(reconcileTimer);
    reconcileTimer = setTimeout(() => {
      reconcileTimer = null;
      void load();
    }, RECONCILE_DEBOUNCE_MS);
  }

  async function load(): Promise<void> {
    loading = true;
    loadError = null;
    deps.setError(null);
    try {
      // Scope to the selected partition. null only when no group exists yet (empty graph) —
      // then the backend default applies and the canvas is simply empty.
      const res = await exportKnowledgeGraph(
        activeGroupId ? { groupIds: [activeGroupId] } : {}
      );
      if (!res.ok || !res.data) {
        loadError = res.error ?? 'Failed to load graph';
        deps.setError(loadError);
        return;
      }
      nodeById.clear();
      edgeById.clear();
      for (const n of res.data.nodes) nodeById.set(n.id, { ...n });
      for (const e of res.data.edges) edgeById.set(e.id, { ...e });
      truncated = res.data.truncated;
      recent = {};
      // Date-range knobs default to the full span of the freshly-loaded data (the spans below
      // re-derive from the new edges); reset so a stale absolute range can't hide the new graph.
      validRange = null;
      creationRange = null;
      rebuildArrays();
      loadVersion += 1; // signal a structural reload to the renderer (full relayout + fit)
      void loadEpisodes(); // refresh the episode picker for this partition (non-blocking)
    } catch (err) {
      loadError = err instanceof Error ? err.message : String(err);
      deps.setError(loadError);
    } finally {
      loading = false;
    }
  }

  /** Fetch the partitions present in the graph and resolve which one to show.
   *  We list whatever groups exist (the backend enumerates DISTINCT group_ids) and pick the
   *  active one: keep the current selection if it still exists, else restore the remembered
   *  one, else default to the FIRST group in the list. `null` only when the graph is empty. */
  async function loadGroups(): Promise<void> {
    const res = await listKnowledgeGraphGroups();
    if (!res.ok || !res.data) return;
    groups = res.data.groups;
    const ids = new Set(groups.map((g) => g.id));
    if (activeGroupId && ids.has(activeGroupId)) return; // keep an explicit current selection
    const remembered = readSessionString(SESSION_ACTIVE_GROUP);
    activeGroupId = remembered && ids.has(remembered) ? remembered : (groups[0]?.id ?? null);
  }

  /** Switch the viewed partition (remembered across opens) and reload (relayout + fit). */
  async function selectGroup(id: string | null): Promise<void> {
    if (id === activeGroupId) return;
    activeGroupId = id;
    // In-memory reset only (NOT clearEpisodes, which would persist-empty and wipe the new
    // group's saved selection); loadEpisodes() restores this partition's persisted selection.
    episodeChunkIds = new Set();
    if (id) writeSessionString(SESSION_ACTIVE_GROUP, id);
    else removeSessionString(SESSION_ACTIVE_GROUP);
    await load();
  }

  /** Load the admin graph-viz display preference (large-type warning threshold). Non-fatal: a
   *  failure keeps the default threshold, since this only tunes a perf heads-up in the filter
   *  dropdowns. Called once when the panel mounts (shared by the Knowledge + Memories graph tabs). */
  async function loadPreferences(): Promise<void> {
    try {
      const res = await getPreferences();
      const t = res.data?.preferences?.graph?.view?.large_type_threshold;
      if (typeof t === 'number' && t > 0) largeTypeThreshold = t;
    } catch (err) {
      console.error('graph: failed to load view preferences', err);
    }
  }

  // Does a live delta belong to the partition we're currently showing? Exact match on the
  // selected group_id — no privileged-default special-casing. When nothing is selected yet
  // (empty graph), deltas wait for the post-ingest reconcile (which re-lists groups).
  function eventMatchesActiveGroup(gid: string | null | undefined): boolean {
    if (activeGroupId === null) return false;
    return (gid ?? '') === activeGroupId;
  }

  function connectEvents(): () => void {
    live = true;
    const disconnect = connectKnowledgeGraphEvents({
      onNode: (e) => {
        if (!eventMatchesActiveGroup(e.group_id)) return;
        pendingNodes.push(e);
        scheduleFlush();
      },
      onEdge: (e) => {
        if (!eventMatchesActiveGroup(e.group_id)) return;
        pendingEdges.push(e);
        scheduleFlush();
      },
      onProgress: (e) => {
        if (!eventMatchesActiveGroup(e.group_id)) return;
        progress = e;
      },
      onCompleted: (gid) => {
        // Always refresh the partition list: a first ingest into an empty graph creates a new
        // group that should appear in the selector (and get auto-selected if none was) — even
        // when the completion is for a partition we're not currently viewing.
        void loadGroups();
        // Clear the "ingesting…" status + reconcile ONLY for the partition we're showing. A
        // bare/legacy emit (gid == null) is treated as global so it still clears. This mirrors
        // onProgress' group gate: a completion for another group must not wipe our status.
        if (gid != null && !eventMatchesActiveGroup(gid)) return;
        progress = null;
        scheduleReconcile();
      }
    });
    return () => {
      live = false;
      progress = null;
      if (reconcileTimer) {
        clearTimeout(reconcileTimer);
        reconcileTimer = null;
      }
      teardownSearch(); // cancel any pending/in-flight chunk-text search
      disconnect();
    };
  }

  function selectNode(id: string): void {
    selected = { kind: 'node', id };
  }
  function selectEdge(id: string): void {
    selected = { kind: 'edge', id };
  }
  function clearSelection(): void {
    selected = null;
  }

  function selectedNode(): GraphNodeDTO | null {
    return selected?.kind === 'node' ? (nodeById.get(selected.id) ?? null) : null;
  }
  function selectedEdge(): GraphEdgeDTO | null {
    return selected?.kind === 'edge' ? (edgeById.get(selected.id) ?? null) : null;
  }
  function nodeName(id: string): string {
    return nodeById.get(id)?.name ?? id;
  }

  // A fact is CURRENT/valid when neither invalidated nor expired — the exact rule the graph
  // search uses (graphiti_search: invalid_at IS NULL AND expired_at IS NULL). Anything with
  // invalid_at or expired_at set is treated as INVALID (superseded / retired).
  function edgeIsCurrent(edge: GraphEdgeDTO): boolean {
    return edge.invalid_at == null && edge.expired_at == null;
  }

  // Does an edge pass an active date-range filter on the given field? An edge WITHOUT that date
  // is governed by the includeUndatedEdges toggle (default: shown). An inactive range (null) is
  // always a pass.
  function passesRange(value: number | null, range: DateRange): boolean {
    if (!range) return true;
    if (value == null) return includeUndatedEdges;
    return value >= range.lo && value <= range.hi;
  }

  // Per-edge visibility (everything EXCEPT the per-node cap, which needs a global pass below):
  // relation type shown, both endpoints shown, validity mode, and the valid_at / created_at
  // date ranges. linkEndId normalizes force-graph's object-ified endpoints back to ids.
  function isEdgeVisible(edge: GraphEdgeDTO): boolean {
    if (hiddenEdgeTypes.has(edge.rel_type)) return false;
    if (hiddenNodeIds.has(linkEndId(edge.source))) return false;
    if (hiddenNodeIds.has(linkEndId(edge.target))) return false;
    if (edgeValidity === 'valid' && !edgeIsCurrent(edge)) return false;
    if (edgeValidity === 'invalid' && edgeIsCurrent(edge)) return false;
    if (!passesRange(epoch(edge.valid_at), validRange)) return false;
    if (!passesRange(epoch(edge.created_at), creationRange)) return false;
    return true;
  }
  function isNodeVisible(node: GraphNodeDTO): boolean {
    return !hiddenNodeIds.has(node.id);
  }

  // Per-type instance groups for the node filter dropdowns. Reflect ALL loaded data (not the
  // filtered subset) so hidden instances stay listed and can be re-checked. One group per node
  // type → one MultiSelectFilter; selectedIds = the visible (un-hidden) instances of that type.
  const nodeInstanceFacets = $derived.by<GraphNodeTypeGroup[]>(() => {
    // Edge degree per node id (how many facts touch it) — drives the per-instance connection
    // count + the dropdown's default "busiest first" sort. Counted over ALL links so the number
    // is stable regardless of the active edge filter.
    const degree = new Map<string, number>();
    for (const e of links) {
      const a = linkEndId(e.source);
      const b = linkEndId(e.target);
      degree.set(a, (degree.get(a) ?? 0) + 1);
      degree.set(b, (degree.get(b) ?? 0) + 1);
    }
    const byType = new Map<string, GraphNodeDTO[]>();
    for (const n of nodes) {
      const arr = byType.get(n.type);
      if (arr) arr.push(n);
      else byType.set(n.type, [n]);
    }
    const groups = [...byType].map(([type, ns]) => {
      // empty name → fall back to id. Order is left to the component (it offers a sort toggle).
      const options = ns.map((n) => ({
        id: n.id,
        name: n.name || n.id,
        connections: degree.get(n.id) ?? 0
      }));
      const selectedIds = options.filter((o) => !hiddenNodeIds.has(o.id)).map((o) => o.id);
      return { type, count: options.length, visibleCount: selectedIds.length, options, selectedIds };
    });
    return groups.sort(
      (a, b) => rankNodeType(a.type) - rankNodeType(b.type) || a.type.localeCompare(b.type)
    );
  });
  const edgeTypeFacets = $derived.by<GraphTypeFacet[]>(() => {
    const counts = new Map<string, number>();
    for (const e of links) counts.set(e.rel_type, (counts.get(e.rel_type) ?? 0) + 1);
    // Busiest relations first, then alphabetical.
    return [...counts]
      .map(([type, count]) => ({ type, count, hidden: hiddenEdgeTypes.has(type) }))
      .sort((a, b) => b.count - a.count || a.type.localeCompare(b.type));
  });

  // Min/max epoch span of each date field across loaded edges (null → no dated edges). Drives the
  // range sliders' bounds; the panel shows a disabled note when null.
  function spanOf(field: 'valid_at' | 'created_at'): { lo: number; hi: number } | null {
    let lo = Infinity;
    let hi = -Infinity;
    for (const e of links) {
      const t = epoch(e[field]);
      if (t == null) continue;
      if (t < lo) lo = t;
      if (t > hi) hi = t;
    }
    return hi >= lo ? { lo, hi } : null;
  }
  const validAtSpan = $derived(spanOf('valid_at'));
  const createdAtSpan = $derived(spanOf('created_at'));

  // The filtered subsets fed to the force-graph instance. Filtering rebuilds the graph from these
  // (recreate + re-layout) so the remaining nodes spread to fill the frame. First apply the
  // per-edge filters (type/instance/validity/date), THEN the per-node connection cap.
  const baseVisibleLinks = $derived(links.filter(isEdgeVisible));

  // Per-node connection cap: keep at most `maxConnPerNode` edges per node. Greedy — walk edges in
  // valid_at order (newest or oldest first; undated last) and keep an edge only if BOTH endpoints
  // are still under the cap, so no node ever exceeds it. Returns null (no cap) at the slider max.
  const cappedEdgeIds = $derived.by<Set<string> | null>(() => {
    if (maxConnPerNode >= MAX_CONN_PER_NODE_CAP) return null;
    const dir = maxConnBy === 'oldest' ? 1 : -1;
    const ranked = [...baseVisibleLinks].sort((a, b) => {
      const ta = epoch(a.valid_at);
      const tb = epoch(b.valid_at);
      if (ta == null && tb == null) return 0;
      if (ta == null) return 1; // undated sinks to the end regardless of direction
      if (tb == null) return -1;
      return (ta - tb) * dir;
    });
    const deg = new Map<string, number>();
    const kept = new Set<string>();
    for (const e of ranked) {
      const a = linkEndId(e.source);
      const b = linkEndId(e.target);
      if ((deg.get(a) ?? 0) < maxConnPerNode && (deg.get(b) ?? 0) < maxConnPerNode) {
        kept.add(e.id);
        deg.set(a, (deg.get(a) ?? 0) + 1);
        deg.set(b, (deg.get(b) ?? 0) + 1);
      }
    }
    return kept;
  });
  // Links surviving all EDGE filters (type / instance / validity / date + per-node cap), BEFORE
  // the orphan node filter prunes their endpoints.
  const edgeFilteredLinks = $derived(
    cappedEdgeIds ? baseVisibleLinks.filter((e) => cappedEdgeIds.has(e.id)) : baseVisibleLinks
  );
  // Visible-degree SNAPSHOT: each node's connection count over the edge-filtered links, computed
  // ONCE (before any low-connection hiding) so the denoise threshold doesn't cascade. A node the
  // per-node cap stripped of all its edges correctly reads degree 0 here. Drives BOTH the denoise
  // filter and (via the engine) the degree-based node sizing — so size reflects what's on screen.
  const visibleDegree = $derived.by<Map<string, number>>(() => {
    const d = new Map<string, number>();
    for (const e of edgeFilteredLinks) {
      const a = linkEndId(e.source);
      const b = linkEndId(e.target);
      d.set(a, (d.get(a) ?? 0) + 1);
      d.set(b, (d.get(b) ?? 0) + 1);
    }
    return d;
  });
  // Busiest node's visible degree — the data-driven MAX for the denoise threshold slider, so its
  // range always reflects the real connection counts in the current graph (not an arbitrary cap).
  const maxVisibleDegree = $derived.by<number>(() => {
    let m = 0;
    for (const v of visibleDegree.values()) if (v > m) m = v;
    return m;
  });
  // A node is "sparse" when its visible degree is below the threshold. threshold 0 ⇒ off (never sparse).
  function isLowConn(id: string): boolean {
    return lowConnThreshold > 0 && (visibleDegree.get(id) ?? 0) < lowConnThreshold;
  }
  // Membership pass: only 'hide' drops nodes; 'dim' keeps everyone (it's render-only). threshold 0
  // makes isLowConn always false, so the graph is unfiltered regardless of treatment (off).
  function lowConnPass(id: string): boolean {
    return lowConnTreatment === 'hide' ? !isLowConn(id) : true;
  }
  const visibleNodes = $derived(nodes.filter((n) => isNodeVisible(n) && lowConnPass(n.id)));
  // Ids the engine should DIM (render-only) — only in 'dim' treatment; 'hide' already dropped them.
  const lowConnDimIds = $derived.by<Set<string>>(() => {
    if (lowConnTreatment !== 'dim') return new Set<string>();
    const s = new Set<string>();
    for (const n of visibleNodes) if (isLowConn(n.id)) s.add(n.id);
    return s;
  });
  // Live "(N nodes)" badge: how many type-visible nodes are sparse, independent of dim-vs-hide so
  // the count is the same either way (computed on the pre-hide snapshot).
  const lowConnCount = $derived.by<number>(() => {
    if (lowConnThreshold <= 0) return 0;
    let c = 0;
    for (const n of nodes) if (isNodeVisible(n) && (visibleDegree.get(n.id) ?? 0) < lowConnThreshold) c++;
    return c;
  });
  const visibleNodeIdSet = $derived(new Set(visibleNodes.map((n) => n.id)));
  // Drop any edge whose endpoint the orphan filter hid — so "only orphans" shows no edges (orphans
  // have none) and a hidden endpoint never leaves a dangling line.
  const visibleLinks = $derived(
    edgeFilteredLinks.filter(
      (e) => visibleNodeIdSet.has(linkEndId(e.source)) && visibleNodeIdSet.has(linkEndId(e.target))
    )
  );
  const visibleNodeCount = $derived(visibleNodes.length);
  const visibleEdgeCount = $derived(visibleLinks.length);

  const edgeFiltersActive = $derived(
    edgeValidity !== 'all' ||
      validRange !== null ||
      creationRange !== null ||
      maxConnPerNode < MAX_CONN_PER_NODE_CAP ||
      lowConnThreshold > 0
  );
  const hasActiveFilters = $derived(
    hiddenNodeIds.size > 0 || hiddenEdgeTypes.size > 0 || edgeFiltersActive
  );
  // Only 'hide' (with a non-zero threshold) changes membership → relayout; 'dim' is render-only, so
  // it's deliberately excluded from filterToken to avoid a needless relayout/fit on every change.
  const denoiseStructuralToken = $derived(
    lowConnTreatment === 'hide' && lowConnThreshold > 0 ? `hide:${lowConnThreshold}` : 'none'
  );
  // A single token that changes whenever any edge filter changes — the renderer treats a change
  // as a STRUCTURAL update (relayout + fit), matching how the node/edge-type filters behave.
  const filterToken = $derived(
    `${edgeValidity}|${includeUndatedEdges}|${maxConnPerNode}|${maxConnBy}|${denoiseStructuralToken}|` +
      `${validRange ? `${validRange.lo}-${validRange.hi}` : 'x'}|` +
      `${creationRange ? `${creationRange.lo}-${creationRange.hi}` : 'x'}`
  );

  // ── Search highlight (transient view state; not persisted) ──────────────────
  // One unified query highlights matching nodes/edges WITHOUT hiding the rest:
  //   • node name/aliases + edge rel_type/fact → matched here (client-side, instant)
  //   • chunk TEXT → matched via a debounced backend lookup (searchGraphChunks returns
  //     point_ids == chunk_ids); we map them onto nodes/edges by chunk_ids. Union below.
  // The query IS the input value (the Graph toolbar binds to searchQuery()), so search
  // state survives a tab switch — there's no panel-local copy to fall out of sync.
  let searchQuery = $state('');
  // Qdrant point_ids whose chunk text matched the current query (== chunk_ids); cleared
  // when the query clears so a stale chunk match never outlives its text.
  let matchedChunkIds = $state<Set<string>>(new Set());
  // ── Episode filter (a second source of matched chunk_ids, beside text search) ──
  // The "Episodes" multi-select picks chunk_ids directly (each episode IS a chunk). Kept
  // SEPARATE from matchedChunkIds: the text leg resets matchedChunkIds on every debounce/
  // clear/abort, which would otherwise wipe an episode selection. Both feed the SAME
  // matched-node/edge derivations (and thus the same highlight/dim/hide focus pipeline).
  let episodes = $state<GraphEpisode[]>([]); // the active group's episodes, in corpus order
  let episodesBusy = $state(false);
  let episodeChunkIds = $state<Set<string>>(new Set()); // selected episode ids (== chunk_ids)
  // True while the debounced backend chunk-text leg is in flight (drives the spinner).
  let searchBusy = $state(false);
  let searchAbort: AbortController | null = null;
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  // Debounced backend chunk-TEXT search. searchGraphChunks THROWS on error/abort, so the
  // rejection must be caught or searchBusy sticks on. Aborted on a newer keystroke / clear.
  function scheduleChunkSearch(term: string): void {
    if (searchTimer) clearTimeout(searchTimer);
    searchAbort?.abort(); // a newer keystroke supersedes the in-flight lookup
    searchAbort = null;
    if (!term) {
      searchBusy = false;
      return;
    }
    searchBusy = true;
    searchTimer = setTimeout(() => {
      const ctrl = new AbortController();
      searchAbort = ctrl;
      void (async () => {
        try {
          const res = await searchGraphChunks(term, ctrl.signal);
          if (ctrl.signal.aborted) return;
          matchedChunkIds = new Set(res.data?.point_ids ?? []);
        } catch (err) {
          if (ctrl.signal.aborted) return; // expected on a newer keystroke / teardown
          console.error('graph chunk-text search failed', err);
          matchedChunkIds = new Set(); // fall back to client-only (name/rel) matches
        } finally {
          if (!ctrl.signal.aborted) searchBusy = false;
        }
      })();
    }, SEARCH_DEBOUNCE_MS);
  }

  // Drive the unified search: instant client-side name/alias + rel_type/fact highlight
  // (via searchQuery), plus the debounced backend chunk-text leg.
  function search(query: string): void {
    searchQuery = query;
    if (!query.trim()) matchedChunkIds = new Set(); // clearing the box clears chunk matches too
    scheduleChunkSearch(query.trim());
  }
  function clearSearch(): void {
    search('');
  }
  // Cancel any pending/in-flight chunk search (called on page teardown).
  function teardownSearch(): void {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = null;
    searchAbort?.abort();
    searchAbort = null;
    searchBusy = false;
  }

  // ── Episode filter ──────────────────────────────────────────────────────────
  // Fetch the active partition's episodes for the multi-select (corpus order). Non-fatal:
  // a failure leaves an empty list so the picker just hides. Called from load() so the list
  // stays in sync with the partition + freshly-ingested episodes.
  async function loadEpisodes(): Promise<void> {
    const gid = activeGroupId;
    if (!gid) {
      episodes = [];
      return;
    }
    episodesBusy = true;
    try {
      const res = await listKnowledgeGraphEpisodes(gid);
      episodes = res.ok && res.data ? res.data.episodes : [];
      // Restore the persisted selection for this partition, dropping any saved ids that no
      // longer exist (the episode list can change as the corpus is re-ingested).
      const present = new Set(episodes.map((e) => e.id));
      const restored = readEpisodeSel(gid).filter((id) => present.has(id));
      episodeChunkIds = new Set(restored);
    } catch (err) {
      console.error('graph: failed to load episodes', err);
      episodes = [];
    } finally {
      episodesBusy = false;
    }
  }
  // Set the selected episodes (chunk_ids) and persist them per-partition (survives refresh).
  // Feeds the SAME matched-node/edge derivations as text search, so the current focus mode
  // (highlight/dim/hide) and match count just apply.
  function setSelectedEpisodes(ids: string[]): void {
    episodeChunkIds = new Set(ids);
    if (activeGroupId) writeEpisodeSel(activeGroupId, ids);
  }
  function clearEpisodes(): void {
    setSelectedEpisodes([]);
  }

  // Active when there's a text query OR an episode selection — both drive the focus pipeline.
  const searchActive = $derived(searchQuery.trim().length > 0 || episodeChunkIds.size > 0);
  // A chunk_id is "matched" if the text leg found it OR it belongs to a selected episode.
  const chunkMatched = (c: string): boolean => matchedChunkIds.has(c) || episodeChunkIds.has(c);

  // Nodes matched: name/alias substring (text leg), OR any chunk_id matched (text or episode).
  // The text legs stay gated on a non-empty q — ''.includes('') is true, so an empty query
  // would otherwise substring-match every node. No query AND no chunk matches ⇒ none.
  const matchedNodeIds = $derived.by<Set<string>>(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q && matchedChunkIds.size === 0 && episodeChunkIds.size === 0) return new Set();
    const out = new Set<string>();
    for (const n of nodes) {
      const textHit =
        !!q && (n.name.toLowerCase().includes(q) || n.aliases.some((a) => a.toLowerCase().includes(q)));
      if (textHit || n.chunk_ids.some(chunkMatched)) out.add(n.id);
    }
    return out;
  });
  // Edges matched: rel_type/fact substring (text leg), OR any chunk_id matched (text or episode).
  const matchedEdgeIds = $derived.by<Set<string>>(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q && matchedChunkIds.size === 0 && episodeChunkIds.size === 0) return new Set();
    const out = new Set<string>();
    for (const e of links) {
      const textHit =
        !!q && (e.rel_type.toLowerCase().includes(q) || (e.fact ?? '').toLowerCase().includes(q));
      if (textHit || e.chunk_ids.some(chunkMatched)) out.add(e.id);
    }
    return out;
  });
  const matchCount = $derived(matchedNodeIds.size + matchedEdgeIds.size);

  // How many graph items (nodes + edges) each episode (chunk_id) contributes, for the episode
  // picker's count badge. Makes "graphless" episodes (which produced no entities/facts, e.g. a
  // chit-chat turn) visibly read 0 so selecting one explains the empty result.
  const episodeItemCounts = $derived.by<Map<string, number>>(() => {
    const m = new Map<string, number>();
    const bump = (ids: string[]): void => {
      for (const c of ids) m.set(c, (m.get(c) ?? 0) + 1);
    };
    for (const n of nodes) bump(n.chunk_ids);
    for (const e of links) bump(e.chunk_ids);
    return m;
  });

  // Node instances are filtered per type via a multi-select dropdown that works in terms of
  // VISIBLE (checked) instance ids. We only touch THIS type's instances: hidden gains the type's
  // unchecked instances and loses its checked ones, leaving other types' hidden ids untouched.
  function setVisibleNodeIds(type: string, visible: string[]): void {
    const shown = new Set(visible);
    const next = new Set(hiddenNodeIds);
    for (const n of nodes) {
      if (n.type !== type) continue;
      if (shown.has(n.id)) next.delete(n.id);
      else next.add(n.id);
    }
    hiddenNodeIds = next;
    writeHidden(SESSION_HIDE_NODES, next);
  }
  // Edge types are filtered via the multi-select dropdown, which works in terms
  // of VISIBLE (checked) types: hidden = (all present edge types) − visible.
  function setVisibleEdgeTypes(visible: string[]): void {
    const shown = new Set(visible);
    const next = new Set<string>();
    for (const e of links) {
      if (!shown.has(e.rel_type)) next.add(e.rel_type);
    }
    hiddenEdgeTypes = next;
    writeHidden(SESSION_HIDE_EDGES, next);
  }
  // ── Edge filter setters (Graph options → Filters). Modes persist; ranges are ephemeral. ──
  function setEdgeValidity(v: EdgeValidity): void {
    edgeValidity = v;
    persistEdgeFilterModes();
  }
  function setIncludeUndatedEdges(on: boolean): void {
    includeUndatedEdges = on;
    persistEdgeFilterModes();
  }
  function setMaxConnPerNode(n: number): void {
    maxConnPerNode = Math.min(MAX_CONN_PER_NODE_CAP, Math.max(1, Math.round(n)));
    persistEdgeFilterModes();
  }
  function setMaxConnBy(by: MaxConnBy): void {
    maxConnBy = by;
    persistEdgeFilterModes();
  }
  // Per-pair "Visible edges" cap. Clamp to [MIN, CAP]; CAP === "All" (no aggregation).
  function setVisibleEdgesPerPair(n: number): void {
    visibleEdgesPerPair = Math.min(VISIBLE_EDGES_CAP, Math.max(VISIBLE_EDGES_MIN, Math.round(n)));
    persistEdgeFilterModes();
  }
  function setLowConnTreatment(t: LowConnTreatment): void {
    lowConnTreatment = t;
    persistEdgeFilterModes();
  }
  function setLowConnThreshold(n: number): void {
    lowConnThreshold = Math.max(LOW_CONN_THRESHOLD_MIN, Math.round(n)); // data-driven max → floor only
    persistEdgeFilterModes();
  }
  // A range equal to (or wider than) the full data span is treated as "inactive" (null) so the
  // slider at both ends never counts as a filter and undated edges aren't gated by it.
  function setValidRange(range: DateRange): void {
    validRange = normalizeRange(range, validAtSpan);
  }
  function setCreationRange(range: DateRange): void {
    creationRange = normalizeRange(range, createdAtSpan);
  }
  function resetEdgeFilters(): void {
    edgeValidity = EDGE_FILTER_DEFAULTS.edgeValidity;
    includeUndatedEdges = EDGE_FILTER_DEFAULTS.includeUndatedEdges;
    maxConnPerNode = EDGE_FILTER_DEFAULTS.maxConnPerNode;
    maxConnBy = EDGE_FILTER_DEFAULTS.maxConnBy;
    visibleEdgesPerPair = EDGE_FILTER_DEFAULTS.visibleEdgesPerPair;
    lowConnTreatment = EDGE_FILTER_DEFAULTS.lowConnTreatment;
    lowConnThreshold = EDGE_FILTER_DEFAULTS.lowConnThreshold;
    validRange = null;
    creationRange = null;
    persistEdgeFilterModes();
  }

  function clearFilters(): void {
    hiddenNodeIds = new Set();
    hiddenEdgeTypes = new Set();
    writeHidden(SESSION_HIDE_NODES, hiddenNodeIds);
    writeHidden(SESSION_HIDE_EDGES, hiddenEdgeTypes);
    resetEdgeFilters();
  }

  return {
    nodes: () => nodes,
    links: () => links,
    loading: () => loading,
    loadError: () => loadError,
    loadVersion: () => loadVersion,
    truncated: () => truncated,
    live: () => live,
    progress: () => progress,
    recent: () => recent,
    selected: () => selected,
    selectedNode,
    selectedEdge,
    nodeName,
    selectNode,
    selectEdge,
    clearSelection,
    load,
    loadPreferences,
    connectEvents,
    // ── group filter ──
    groups: () => groups,
    activeGroupId: () => activeGroupId,
    loadGroups,
    selectGroup,
    // ── view filters ──
    nodeInstanceFacets: () => nodeInstanceFacets,
    edgeTypeFacets: () => edgeTypeFacets,
    largeTypeThreshold: () => largeTypeThreshold,
    hiddenNodeIds: () => hiddenNodeIds,
    hiddenEdgeTypes: () => hiddenEdgeTypes,
    visibleNodes: () => visibleNodes,
    visibleLinks: () => visibleLinks,
    visibleNodeCount: () => visibleNodeCount,
    visibleEdgeCount: () => visibleEdgeCount,
    hasActiveFilters: () => hasActiveFilters,
    setVisibleNodeIds,
    setVisibleEdgeTypes,
    clearFilters,
    // ── edge filters (Graph options → Filters) ──
    filterToken: () => filterToken,
    edgeValidity: () => edgeValidity,
    includeUndatedEdges: () => includeUndatedEdges,
    maxConnPerNode: () => maxConnPerNode,
    maxConnBy: () => maxConnBy,
    visibleEdgesPerPair: () => visibleEdgesPerPair,
    lowConnTreatment: () => lowConnTreatment,
    lowConnThreshold: () => lowConnThreshold,
    lowConnDimIds: () => lowConnDimIds,
    lowConnCount: () => lowConnCount,
    maxVisibleDegree: () => maxVisibleDegree,
    validRange: () => validRange,
    creationRange: () => creationRange,
    validAtSpan: () => validAtSpan,
    createdAtSpan: () => createdAtSpan,
    setEdgeValidity,
    setIncludeUndatedEdges,
    setMaxConnPerNode,
    setMaxConnBy,
    setVisibleEdgesPerPair,
    setLowConnTreatment,
    setLowConnThreshold,
    setValidRange,
    setCreationRange,
    resetEdgeFilters,
    // ── search highlight ──
    searchQuery: () => searchQuery,
    searchBusy: () => searchBusy,
    search,
    clearSearch,
    searchActive: () => searchActive,
    matchedNodeIds: () => matchedNodeIds,
    matchedEdgeIds: () => matchedEdgeIds,
    matchCount: () => matchCount,
    // ── episode filter ──
    episodes: () => episodes,
    episodesBusy: () => episodesBusy,
    episodeItemCount: (id: string) => episodeItemCounts.get(id) ?? 0,
    selectedEpisodeIds: () => [...episodeChunkIds],
    setSelectedEpisodes,
    clearEpisodes
  };
}

export type KnowledgeGraphModel = ReturnType<typeof createKnowledgeGraphModel>;
