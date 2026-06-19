import { describe, expect, it } from 'vitest';
import type { FgLink, FgNode } from '../../graph/engine/graph-types';
import type { RenderLink, RenderNode } from '../../graph/engine/graph-engine-types';
import {
  computeDegreeMap,
  computeOuterRing,
  reconcileMirrors
} from '../../graph/engine/graph-reconcile';

function renderNode(id: string, type = 'Person', name = id): RenderNode {
  return { id, type, name };
}

function renderLink(
  id: string,
  source: string,
  target: string,
  rel = 'RELATES_TO',
  invalid_at: string | null = null
): RenderLink {
  return { id, source, target, rel_type: rel, invalid_at, expired_at: null };
}

describe('reconcileMirrors', () => {
  it('adds new nodes and links to mirror maps', () => {
    const fgNodeById = new Map<string, FgNode>();
    const fgLinkById = new Map<string, FgLink>();
    const rNodes = [renderNode('a'), renderNode('b')];
    const rLinks = [renderLink('e1', 'a', 'b')];

    const { fgNodes, fgLinks, freshNodeIds } = reconcileMirrors(
      rNodes,
      rLinks,
      fgNodeById,
      fgLinkById
    );

    expect(fgNodes.map((n) => n.id)).toEqual(['a', 'b']);
    expect(fgLinks.map((l) => l.id)).toEqual(['e1']);
    expect(freshNodeIds).toEqual(['a', 'b']);
    expect(fgNodeById.has('a')).toBe(true);
    expect(fgLinkById.get('e1')?.invalid).toBe(false);
  });

  it('updates existing mirror fields and removes stale entries', () => {
    const fgNodeById = new Map<string, FgNode>([
      ['a', { id: 'a', type: 'Person', name: 'old' }],
      ['stale', { id: 'stale', type: 'Entity', name: 'gone' }]
    ]);
    const fgLinkById = new Map<string, FgLink>([
      ['e-old', { id: 'e-old', source: 'a', target: 'b', rel_type: 'OLD', invalid: false }]
    ]);

    const rNodes = [renderNode('a', 'Person', 'Alice')];
    const rLinks = [renderLink('e1', 'a', 'b', 'NEW', '2024-01-01T00:00:00.000Z')];

    reconcileMirrors(rNodes, rLinks, fgNodeById, fgLinkById);

    expect(fgNodeById.has('stale')).toBe(false);
    expect(fgNodeById.get('a')?.name).toBe('Alice');
    expect(fgLinkById.has('e-old')).toBe(false);
    expect(fgLinkById.get('e1')?.rel_type).toBe('NEW');
    expect(fgLinkById.get('e1')?.invalid).toBe(true);
  });

  it('does not report existing nodes as fresh on update', () => {
    const fgNodeById = new Map<string, FgNode>([['a', { id: 'a', type: 'Person', name: 'a' }]]);
    const fgLinkById = new Map<string, FgLink>();

    const { freshNodeIds } = reconcileMirrors(
      [renderNode('a'), renderNode('b')],
      [],
      fgNodeById,
      fgLinkById
    );

    expect(freshNodeIds).toEqual(['b']);
  });
});

describe('computeDegreeMap', () => {
  it('counts both endpoints per link', () => {
    const links: FgLink[] = [
      { id: 'e1', source: 'a', target: 'b', rel_type: 'R', invalid: false },
      { id: 'e2', source: 'a', target: 'c', rel_type: 'R', invalid: false }
    ];
    const degree = computeDegreeMap(links);
    expect(degree.get('a')).toBe(2);
    expect(degree.get('b')).toBe(1);
    expect(degree.get('c')).toBe(1);
  });
});

describe('computeOuterRing', () => {
  it('scales radial ring by sqrt(node count)', () => {
    expect(computeOuterRing(100, 1)).toBe(100);
    expect(computeOuterRing(100, 4)).toBe(200);
  });
});
