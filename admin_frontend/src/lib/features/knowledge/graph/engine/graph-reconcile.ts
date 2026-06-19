import {
  HUB_BAND_FRACTION,
  HUB_BAND_FRACTION_MAX,
  collideRadius
} from './graph-forces';
import { linkEndId, type FgLink, type FgNode } from './graph-types';
import type { RenderLink, RenderNode } from './graph-engine-types';

export type ReconcileParams = {
  hubSeparation: number;
  hubSpacing: number;
  collideScale: number;
  radiusForDegree: (degree: number) => number;
};

export function reconcileMirrors(
  rNodes: RenderNode[],
  rLinks: RenderLink[],
  fgNodeById: Map<string, FgNode>,
  fgLinkById: Map<string, FgLink>
): { fgNodes: FgNode[]; fgLinks: FgLink[]; freshNodeIds: string[] } {
  const fgNodes: FgNode[] = [];
  const freshNodeIds: string[] = [];
  const nodeIds = new Set<string>();
  for (const n of rNodes) {
    nodeIds.add(n.id);
    let m = fgNodeById.get(n.id);
    if (!m) {
      m = { id: n.id, type: n.type, name: n.name };
      fgNodeById.set(n.id, m);
      freshNodeIds.push(n.id);
    } else {
      m.type = n.type;
      m.name = n.name;
    }
    fgNodes.push(m);
  }
  for (const id of [...fgNodeById.keys()]) if (!nodeIds.has(id)) fgNodeById.delete(id);

  const fgLinks: FgLink[] = [];
  const linkIds = new Set<string>();
  for (const l of rLinks) {
    linkIds.add(l.id);
    const invalid = !!(l.invalid_at || l.expired_at);
    let m = fgLinkById.get(l.id);
    if (!m) {
      m = {
        id: l.id,
        source: linkEndId(l.source),
        target: linkEndId(l.target),
        rel_type: l.rel_type,
        invalid,
        aggregate: l.aggregate,
        collapsedIds: l.collapsedIds,
        whole: l.whole
      };
      fgLinkById.set(l.id, m);
    } else {
      m.rel_type = l.rel_type;
      m.invalid = invalid;
      m.aggregate = l.aggregate;
      m.collapsedIds = l.collapsedIds;
      m.whole = l.whole;
    }
    fgLinks.push(m);
  }
  for (const id of [...fgLinkById.keys()]) if (!linkIds.has(id)) fgLinkById.delete(id);

  return { fgNodes, fgLinks, freshNodeIds };
}

export function assignNodeTarget(
  n: FgNode,
  degree: Map<string, number>,
  maxDegree: number,
  outerRing: number,
  params: ReconcileParams
): void {
  const d = degree.get(n.id) ?? 0;
  n.__degree = d;
  n.__collideR = collideRadius(
    d,
    params.hubSeparation,
    params.hubSpacing,
    params.radiusForDegree(d),
    params.collideScale
  );
  const bandFraction = Math.min(HUB_BAND_FRACTION * params.hubSpacing, HUB_BAND_FRACTION_MAX);
  const innerBand = outerRing * bandFraction * params.hubSeparation;
  n.__targetR = innerBand + (1 - d / maxDegree) * (outerRing - innerBand);
}

export function seedNewNodePositions(
  newNodes: FgNode[],
  links: FgLink[],
  placed: Map<string, FgNode>
): void {
  if (newNodes.length === 0) return;
  const newIds = new Set(newNodes.map((n) => n.id));
  const acc = new Map<string, { x: number; y: number; n: number }>();
  for (const l of links) {
    const a = String(linkEndId(l.source));
    const b = String(linkEndId(l.target));
    if (newIds.has(a) && !newIds.has(b)) addNeighbour(acc, placed, a, b);
    if (newIds.has(b) && !newIds.has(a)) addNeighbour(acc, placed, b, a);
  }
  for (const n of newNodes) {
    const e = acc.get(n.id);
    if (e && e.n > 0) {
      const jitter = () => (Math.random() - 0.5) * 70;
      n.x = e.x / e.n + jitter();
      n.y = e.y / e.n + jitter();
    }
  }
}

function addNeighbour(
  acc: Map<string, { x: number; y: number; n: number }>,
  placed: Map<string, FgNode>,
  newId: string,
  otherId: string
): void {
  const other = placed.get(otherId);
  if (!other || other.x == null || other.y == null) return;
  const e = acc.get(newId) ?? { x: 0, y: 0, n: 0 };
  e.x += other.x;
  e.y += other.y;
  e.n += 1;
  acc.set(newId, e);
}

export function computeDegreeMap(links: FgLink[]): Map<string, number> {
  const degree = new Map<string, number>();
  for (const l of links) {
    const a = linkEndId(l.source);
    const b = linkEndId(l.target);
    degree.set(a, (degree.get(a) ?? 0) + 1);
    degree.set(b, (degree.get(b) ?? 0) + 1);
  }
  return degree;
}

export function computeOuterRing(radialRing: number, nodeCount: number): number {
  return radialRing * Math.max(1, Math.sqrt(nodeCount));
}
