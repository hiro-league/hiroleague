import type { GraphEdgeDTO, GraphNodeDTO } from '$lib/api/knowledge';
import { KNOWN_NODE_TYPE_ORDER } from '../../graph/knowledge-graph-style';
import { linkEndId } from '../../graph/engine/graph-types';
import {
  MAX_CONN_PER_NODE_CAP,
  type DateRange,
  type EdgeValidity,
  type GraphNodeTypeGroup,
  type GraphTypeFacet,
  type LowConnTreatment,
  type MaxConnBy
} from './graph-types';

/** Parse an ISO timestamp to epoch ms, or null when absent/unparseable. */
export function epoch(iso: string | null): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

/** Clamp a date range to the data span; collapse to null when it covers the full span. */
export function normalizeRange(
  range: DateRange,
  span: { lo: number; hi: number } | null
): DateRange {
  if (!range || !span) return null;
  const tol = Math.max(1, (span.hi - span.lo) / 100);
  const lo = Math.max(span.lo, Math.min(range.lo, range.hi));
  const hi = Math.min(span.hi, Math.max(range.lo, range.hi));
  const atStart = lo <= span.lo + tol;
  const atEnd = hi >= span.hi - tol;
  if (atStart && atEnd) return null;
  return { lo: atStart ? span.lo : lo, hi: atEnd ? span.hi : hi };
}

export function spanOf(
  links: GraphEdgeDTO[],
  field: 'valid_at' | 'created_at'
): { lo: number; hi: number } | null {
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

export function rankNodeType(t: string): number {
  const i = KNOWN_NODE_TYPE_ORDER.indexOf(t);
  return i === -1 ? KNOWN_NODE_TYPE_ORDER.length : i;
}

export function edgeIsCurrent(edge: GraphEdgeDTO): boolean {
  return edge.invalid_at == null && edge.expired_at == null;
}

export function passesRange(
  value: number | null,
  range: DateRange,
  includeUndatedEdges: boolean
): boolean {
  if (!range) return true;
  if (value == null) return includeUndatedEdges;
  return value >= range.lo && value <= range.hi;
}

export type EdgeVisibilityContext = {
  hiddenEdgeTypes: Set<string>;
  hiddenNodeIds: Set<string>;
  edgeValidity: EdgeValidity;
  includeUndatedEdges: boolean;
  validRange: DateRange;
  creationRange: DateRange;
};

export function isEdgeVisible(edge: GraphEdgeDTO, ctx: EdgeVisibilityContext): boolean {
  if (ctx.hiddenEdgeTypes.has(edge.rel_type)) return false;
  if (ctx.hiddenNodeIds.has(linkEndId(edge.source))) return false;
  if (ctx.hiddenNodeIds.has(linkEndId(edge.target))) return false;
  if (ctx.edgeValidity === 'valid' && !edgeIsCurrent(edge)) return false;
  if (ctx.edgeValidity === 'invalid' && edgeIsCurrent(edge)) return false;
  if (!passesRange(epoch(edge.valid_at), ctx.validRange, ctx.includeUndatedEdges)) return false;
  if (!passesRange(epoch(edge.created_at), ctx.creationRange, ctx.includeUndatedEdges)) return false;
  return true;
}

export function isNodeVisible(node: GraphNodeDTO, hiddenNodeIds: Set<string>): boolean {
  return !hiddenNodeIds.has(node.id);
}

export function computeNodeDegree(links: GraphEdgeDTO[]): Map<string, number> {
  const degree = new Map<string, number>();
  for (const e of links) {
    const a = linkEndId(e.source);
    const b = linkEndId(e.target);
    degree.set(a, (degree.get(a) ?? 0) + 1);
    degree.set(b, (degree.get(b) ?? 0) + 1);
  }
  return degree;
}

export function computeNodeInstanceFacets(
  nodes: GraphNodeDTO[],
  links: GraphEdgeDTO[],
  hiddenNodeIds: Set<string>
): GraphNodeTypeGroup[] {
  const degree = computeNodeDegree(links);
  const byType = new Map<string, GraphNodeDTO[]>();
  for (const n of nodes) {
    const arr = byType.get(n.type);
    if (arr) arr.push(n);
    else byType.set(n.type, [n]);
  }
  const groups = [...byType].map(([type, ns]) => {
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
}

export function computeEdgeTypeFacets(
  links: GraphEdgeDTO[],
  hiddenEdgeTypes: Set<string>
): GraphTypeFacet[] {
  const counts = new Map<string, number>();
  for (const e of links) counts.set(e.rel_type, (counts.get(e.rel_type) ?? 0) + 1);
  return [...counts]
    .map(([type, count]) => ({ type, count, hidden: hiddenEdgeTypes.has(type) }))
    .sort((a, b) => b.count - a.count || a.type.localeCompare(b.type));
}

export function computeCappedEdgeIds(
  baseVisibleLinks: GraphEdgeDTO[],
  maxConnPerNode: number,
  maxConnBy: MaxConnBy
): Set<string> | null {
  if (maxConnPerNode >= MAX_CONN_PER_NODE_CAP) return null;
  const dir = maxConnBy === 'oldest' ? 1 : -1;
  const ranked = [...baseVisibleLinks].sort((a, b) => {
    const ta = epoch(a.valid_at);
    const tb = epoch(b.valid_at);
    if (ta == null && tb == null) return 0;
    if (ta == null) return 1;
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
}

export function computeVisibleDegree(edgeFilteredLinks: GraphEdgeDTO[]): Map<string, number> {
  const d = new Map<string, number>();
  for (const e of edgeFilteredLinks) {
    const a = linkEndId(e.source);
    const b = linkEndId(e.target);
    d.set(a, (d.get(a) ?? 0) + 1);
    d.set(b, (d.get(b) ?? 0) + 1);
  }
  return d;
}

export function maxMapValue(m: Map<string, number>): number {
  let max = 0;
  for (const v of m.values()) if (v > max) max = v;
  return max;
}

export function isLowConn(
  id: string,
  lowConnThreshold: number,
  visibleDegree: Map<string, number>
): boolean {
  return lowConnThreshold > 0 && (visibleDegree.get(id) ?? 0) < lowConnThreshold;
}

export function lowConnPass(
  id: string,
  lowConnTreatment: LowConnTreatment,
  lowConnThreshold: number,
  visibleDegree: Map<string, number>
): boolean {
  return lowConnTreatment === 'hide'
    ? !isLowConn(id, lowConnThreshold, visibleDegree)
    : true;
}

export function computeLowConnDimIds(
  visibleNodes: GraphNodeDTO[],
  lowConnTreatment: LowConnTreatment,
  lowConnThreshold: number,
  visibleDegree: Map<string, number>
): Set<string> {
  if (lowConnTreatment !== 'dim') return new Set<string>();
  const s = new Set<string>();
  for (const n of visibleNodes) {
    if (isLowConn(n.id, lowConnThreshold, visibleDegree)) s.add(n.id);
  }
  return s;
}

export function computeLowConnCount(
  nodes: GraphNodeDTO[],
  hiddenNodeIds: Set<string>,
  lowConnThreshold: number,
  visibleDegree: Map<string, number>
): number {
  if (lowConnThreshold <= 0) return 0;
  let c = 0;
  for (const n of nodes) {
    if (isNodeVisible(n, hiddenNodeIds) && (visibleDegree.get(n.id) ?? 0) < lowConnThreshold) c++;
  }
  return c;
}

export type MatchContext = {
  searchQuery: string;
  matchedChunkIds: Set<string>;
  episodeChunkIds: Set<string>;
};

function chunkMatched(c: string, ctx: MatchContext): boolean {
  return ctx.matchedChunkIds.has(c) || ctx.episodeChunkIds.has(c);
}

export function computeMatchedNodeIds(nodes: GraphNodeDTO[], ctx: MatchContext): Set<string> {
  const q = ctx.searchQuery.trim().toLowerCase();
  if (!q && ctx.matchedChunkIds.size === 0 && ctx.episodeChunkIds.size === 0) return new Set();
  const out = new Set<string>();
  for (const n of nodes) {
    const textHit =
      !!q &&
      (n.name.toLowerCase().includes(q) ||
        n.aliases.some((a) => a.toLowerCase().includes(q)));
    if (textHit || n.chunk_ids.some((c) => chunkMatched(c, ctx))) out.add(n.id);
  }
  return out;
}

export function computeMatchedEdgeIds(links: GraphEdgeDTO[], ctx: MatchContext): Set<string> {
  const q = ctx.searchQuery.trim().toLowerCase();
  if (!q && ctx.matchedChunkIds.size === 0 && ctx.episodeChunkIds.size === 0) return new Set();
  const out = new Set<string>();
  for (const e of links) {
    const textHit =
      !!q &&
      (e.rel_type.toLowerCase().includes(q) || (e.fact ?? '').toLowerCase().includes(q));
    if (textHit || e.chunk_ids.some((c) => chunkMatched(c, ctx))) out.add(e.id);
  }
  return out;
}

export function computeEpisodeItemCounts(
  nodes: GraphNodeDTO[],
  links: GraphEdgeDTO[]
): Map<string, number> {
  const m = new Map<string, number>();
  const bump = (ids: string[]): void => {
    for (const c of ids) m.set(c, (m.get(c) ?? 0) + 1);
  };
  for (const n of nodes) bump(n.chunk_ids);
  for (const e of links) bump(e.chunk_ids);
  return m;
}

export function buildFilterToken(input: {
  edgeValidity: EdgeValidity;
  includeUndatedEdges: boolean;
  maxConnPerNode: number;
  maxConnBy: MaxConnBy;
  lowConnTreatment: LowConnTreatment;
  lowConnThreshold: number;
  validRange: DateRange;
  creationRange: DateRange;
}): string {
  const denoiseStructuralToken =
    input.lowConnTreatment === 'hide' && input.lowConnThreshold > 0
      ? `hide:${input.lowConnThreshold}`
      : 'none';
  return (
    `${input.edgeValidity}|${input.includeUndatedEdges}|${input.maxConnPerNode}|${input.maxConnBy}|${denoiseStructuralToken}|` +
    `${input.validRange ? `${input.validRange.lo}-${input.validRange.hi}` : 'x'}|` +
    `${input.creationRange ? `${input.creationRange.lo}-${input.creationRange.hi}` : 'x'}`
  );
}

export function edgeFiltersActive(input: {
  edgeValidity: EdgeValidity;
  validRange: DateRange;
  creationRange: DateRange;
  maxConnPerNode: number;
  lowConnThreshold: number;
}): boolean {
  return (
    input.edgeValidity !== 'all' ||
    input.validRange !== null ||
    input.creationRange !== null ||
    input.maxConnPerNode < MAX_CONN_PER_NODE_CAP ||
    input.lowConnThreshold > 0
  );
}
