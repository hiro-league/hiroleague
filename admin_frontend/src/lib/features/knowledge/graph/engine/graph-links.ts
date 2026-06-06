/**
 * Pure parallel-edge geometry helpers for the knowledge graph engine.
 *
 * When 2+ edges share the same node pair they'd overlap as one straight line; these fan
 * them into distinct arcs (assignLinkCurvatures) and cap how many are drawn per pair
 * (capParallelLinks). No force-graph / render state — just topology math.
 */
import { SELF_LOOP_BASE, SELF_LOOP_STEP } from './graph-config';
import { MAX_LINKS_CAP } from '../knowledge-graph-prefs';
import { linkEndId, type FgLink } from './graph-types';

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

/**
 * Cap how many parallel edges are drawn between any node pair (and per self-loop) so a
 * densely-connected pair doesn't render as an unreadable fan. Keeps the first `max` edges
 * per group in visible-link order. max >= MAX_LINKS_CAP means "show all" (no cap).
 */
export function capParallelLinks<T extends { source: unknown; target: unknown }>(
  links: T[],
  max: number
): T[] {
  if (max >= MAX_LINKS_CAP) return links; // sentinel: unlimited
  const counts = new Map<string, number>();
  const out: T[] = [];
  for (const l of links) {
    const key = pairKey(String(linkEndId(l.source)), String(linkEndId(l.target)));
    const n = counts.get(key) ?? 0;
    if (n >= max) continue; // pair already at the cap → drop this edge
    counts.set(key, n + 1);
    out.push(l);
  }
  return out;
}
