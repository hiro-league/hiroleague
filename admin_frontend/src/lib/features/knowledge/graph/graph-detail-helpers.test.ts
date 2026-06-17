import { describe, it, expect } from 'vitest';
import type { GraphEdgeDTO } from '$lib/api/knowledge';
import {
  collapsedEdges,
  connectionsForNode,
  hasMatch,
  highlightParts
} from './graph-detail-helpers';

const edge = (over: Partial<GraphEdgeDTO>): GraphEdgeDTO => ({
  id: 'e',
  source: 'a',
  target: 'b',
  rel_type: 'REL',
  fact: '',
  chunk_ids: [],
  document_ids: [],
  valid_at: null,
  invalid_at: null,
  expired_at: null,
  created_at: null,
  ...over
});

describe('highlightParts', () => {
  it('blank query → one non-match run (renders plainly)', () => {
    expect(highlightParts('hello', '  ')).toEqual([{ text: 'hello', match: false }]);
  });

  it('splits a case-insensitive match into runs', () => {
    expect(highlightParts('Hello World', 'world')).toEqual([
      { text: 'Hello ', match: false },
      { text: 'World', match: true }
    ]);
  });

  it('flags every occurrence', () => {
    const parts = highlightParts('a-A-a', 'a');
    expect(parts.filter((p) => p.match).map((p) => p.text)).toEqual(['a', 'A', 'a']);
  });

  it('hasMatch is case-insensitive and false for blank', () => {
    expect(hasMatch('Foo Bar', 'bar')).toBe(true);
    expect(hasMatch('Foo Bar', '   ')).toBe(false);
  });
});

describe('connectionsForNode', () => {
  const edges: GraphEdgeDTO[] = [
    edge({ id: 'e1', source: 'n', target: 'x', rel_type: 'KNOWS' }),
    edge({ id: 'e2', source: 'y', target: 'n', rel_type: 'AVOIDS', invalid_at: '2020-01-01' }),
    edge({ id: 'e3', source: 'p', target: 'q', rel_type: 'OTHER' }) // doesn't touch n
  ];

  it('keeps only edges touching the node, with neighbor + direction', () => {
    const rows = connectionsForNode('n', edges);
    expect(rows.map((r) => r.edgeId)).toEqual(['e1', 'e2']); // current before superseded
    const e1 = rows.find((r) => r.edgeId === 'e1')!;
    expect(e1).toMatchObject({ neighborId: 'x', outgoing: true, invalid: false });
    const e2 = rows.find((r) => r.edgeId === 'e2')!;
    expect(e2).toMatchObject({ neighborId: 'y', outgoing: false, invalid: true });
  });

  it('self-loops list the node as its own neighbor', () => {
    const rows = connectionsForNode('n', [edge({ id: 'self', source: 'n', target: 'n' })]);
    expect(rows[0]).toMatchObject({ neighborId: 'n', outgoing: true });
  });
});

describe('collapsedEdges', () => {
  it('resolves collapsedIds to edges, skips missing, sorts current-first', () => {
    const map = new Map<string, GraphEdgeDTO>([
      ['a', edge({ id: 'a', rel_type: 'B', expired_at: '2020-01-01' })],
      ['b', edge({ id: 'b', rel_type: 'A' })]
    ]);
    const out = collapsedEdges(['a', 'b', 'missing'], map);
    expect(out.map((e) => e.id)).toEqual(['b', 'a']); // current 'b' before superseded 'a'
  });
});
