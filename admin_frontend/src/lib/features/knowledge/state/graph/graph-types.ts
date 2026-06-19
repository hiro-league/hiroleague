/** Shared types and constants for the knowledge graph model. */

export type GraphSelection =
  | { kind: 'node'; id: string }
  | { kind: 'edge'; id: string }
  | null;

/** One row of the edge-type filter strip: a type, how many carry it, hidden state. */
export type GraphTypeFacet = { type: string; count: number; hidden: boolean };

/** One node-type group for the per-type instance filter. */
export type GraphNodeInstanceOption = {
  id: string;
  name: string;
  connections: number;
};

export type GraphNodeTypeGroup = {
  type: string;
  count: number;
  visibleCount: number;
  options: GraphNodeInstanceOption[];
  selectedIds: string[];
};

/** Edge validity filter (current fact rule: invalid_at AND expired_at both null). */
export type EdgeValidity = 'all' | 'valid' | 'invalid';

/** Which edges to keep when a connection cap kicks in. */
export type MaxConnBy = 'newest' | 'oldest';

/** Denoise treatment for sparse (low-connection) nodes. */
export type LowConnTreatment = 'dim' | 'hide';

/** Inclusive epoch-ms range for a date slider; null = inactive (full span). */
export type DateRange = { lo: number; hi: number } | null;

export const LOW_CONN_THRESHOLD_MIN = 0;
export const LOW_CONN_THRESHOLD_DEFAULT = 0;

export const MAX_CONN_PER_NODE_CAP = 25;
export const VISIBLE_EDGES_CAP = 100;
export const VISIBLE_EDGES_MIN = 1;

export const DEFAULT_LARGE_TYPE_THRESHOLD = 200;
export const RECONCILE_DEBOUNCE_MS = 400;
export const SEARCH_DEBOUNCE_MS = 250;

/** Persisted edge-filter MODES (date ranges are ephemeral per load). */
export type EdgeFilterModes = {
  edgeValidity: EdgeValidity;
  includeUndatedEdges: boolean;
  maxConnPerNode: number;
  maxConnBy: MaxConnBy;
  visibleEdgesPerPair: number;
  lowConnTreatment: LowConnTreatment;
  lowConnThreshold: number;
};

export const EDGE_FILTER_DEFAULTS: EdgeFilterModes = {
  edgeValidity: 'all',
  includeUndatedEdges: true,
  maxConnPerNode: MAX_CONN_PER_NODE_CAP,
  maxConnBy: 'newest',
  visibleEdgesPerPair: VISIBLE_EDGES_CAP,
  lowConnTreatment: 'dim',
  lowConnThreshold: LOW_CONN_THRESHOLD_DEFAULT
};
