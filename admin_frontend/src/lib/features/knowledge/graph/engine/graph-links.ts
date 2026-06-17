/**
 * Pure parallel-edge geometry helpers for the knowledge graph engine.
 *
 * When 2+ edges share the same node pair they'd overlap as one straight line; these fan
 * them into distinct arcs (assignLinkCurvatures) and collapse the ones past a pair's
 * "Visible edges" cap into one aggregate edge (collapseParallelLinks). No force-graph /
 * render state — just topology math.
 */
import { SELF_LOOP_BASE, SELF_LOOP_STEP } from './graph-config';
import { linkEndId, type FgLink } from './graph-types';

/** A synthetic edge standing in for the parallel edges a pair's "Visible edges" cap collapsed.
 *  It sits on the same node pair, renders as a thicker solid "N other relations" line, and
 *  carries the ids of the edges it represents (`collapsedIds`) — unused for now by design. */
export interface AggregateLink {
  id: string;
  source: string;
  target: string;
  rel_type: '';
  aggregate: true;
  /** Ids of the parallel edges this aggregate stands in for (length === the "N" in the label). */
  collapsedIds: string[];
  /** True when this aggregate represents ALL of the pair's relations (no real edge shown alongside,
   *  i.e. "max visible edges" === 1) → labelled "X relations" instead of "N other relations". */
  whole: boolean;
}

/** Group key for an UNORDERED node pair so A→B and B→A fan together; self-loops separate.
 *  The space delimiter can't collide with an id (ids never contain a bare space here). */
function pairKey(a: string, b: string): string {
  return a === b ? `self ${a}` : a < b ? `${a} ${b}` : `${b} ${a}`;
}

/**
 * Assign each link a `__curvature` (read by force-graph per frame) so parallel edges fan
 * into separate arcs. `curveAmount` is the outer bow (the "Edge curvature" control).
 */
export function assignLinkCurvatures(links: FgLink[], curveAmount: number): void {
  const groups = new Map<string, FgLink[]>();
  for (const l of links) {
    const key = pairKey(String(linkEndId(l.source)), String(linkEndId(l.target)));
    const g = groups.get(key);
    if (g) g.push(l);
    else groups.set(key, [l]);
  }
  for (const [key, group] of groups) {
    if (key.startsWith('self ')) {
      // Self-loops: stack increasing loop sizes so multiples don't coincide.
      group.forEach((l, i) => (l.__curvature = SELF_LOOP_BASE + i * SELF_LOOP_STEP));
      continue;
    }
    if (group.length === 1) {
      group[0].__curvature = 0; // lone edge stays straight
      continue;
    }
    // Symmetric fan from −curveAmount…+curveAmount (one straight when odd count);
    // opposite-direction edges flip sign so reciprocals separate.
    const last = group.length - 1;
    const refSource = linkEndId(group[last].source);
    group[last].__curvature = curveAmount;
    const delta = (2 * curveAmount) / last;
    for (let i = 0; i < last; i++) {
      let c = -curveAmount + i * delta;
      if (linkEndId(group[i].source) !== refSource) c *= -1;
      group[i].__curvature = c;
    }
  }
}

/** Parse an ISO timestamp to epoch ms, or null when absent/unparseable (undated). */
function epochOf(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

/**
 * "Max visible edges between nodes" per entity pair. For each node pair (and self-loop) with more
 * than `visibleEdges` edges, keep `visibleEdges − 1` real edges (the newest or oldest by valid_at,
 * per `keepBy`) and fold the remainder into ONE synthetic `AggregateLink` on the same pair, carrying
 * the collapsed ids. At `visibleEdges === 1` no real edge is kept, so the aggregate stands in for the
 * WHOLE pair ("X relations"); at 2+ it's the leftover ("N other relations"). A pair at or under the
 * value is shown in full (e.g. 2 edges, value 2 → both, no aggregate). `visibleEdges >= cap` means
 * "show all" (no aggregation). Operates AFTER all model filters, on the display list.
 */
export function collapseParallelLinks<
  T extends { id: string; source: unknown; target: unknown; valid_at?: string | null }
>(links: T[], visibleEdges: number, keepBy: 'newest' | 'oldest', cap: number): (T | AggregateLink)[] {
  if (visibleEdges >= cap) return links; // sentinel: unlimited → no aggregation

  // Group edges by their UNORDERED pair so A→B and B→A collapse together (matches the fan logic).
  const groups = new Map<string, T[]>();
  for (const l of links) {
    const key = pairKey(String(linkEndId(l.source)), String(linkEndId(l.target)));
    const g = groups.get(key);
    if (g) g.push(l);
    else groups.set(key, [l]);
  }

  const dir = keepBy === 'oldest' ? 1 : -1;
  const out: (T | AggregateLink)[] = [];
  for (const [key, group] of groups) {
    if (group.length <= visibleEdges) {
      out.push(...group); // pair fits the cap → show every edge, no aggregate
      continue;
    }
    // Rank by valid_at (newest or oldest first; undated sinks to the end), keep the top V−1.
    const ranked = [...group].sort((a, b) => {
      const ta = epochOf(a.valid_at);
      const tb = epochOf(b.valid_at);
      if (ta == null && tb == null) return 0;
      if (ta == null) return 1;
      if (tb == null) return -1;
      return (ta - tb) * dir;
    });
    const kept = ranked.slice(0, visibleEdges - 1);
    const collapsed = ranked.slice(visibleEdges - 1);
    out.push(...kept);
    // Aggregate sits on the same pair; a stable id (per pair) keeps the engine mirror's identity
    // across rebuilds so it doesn't re-fan/jump when the slider or filters change.
    out.push({
      id: `__agg:${key}`,
      source: linkEndId(group[0].source),
      target: linkEndId(group[0].target),
      rel_type: '',
      aggregate: true,
      collapsedIds: collapsed.map((e) => e.id),
      whole: kept.length === 0 // value 1 → no real edge shown → "X relations"
    });
  }
  return out;
}
