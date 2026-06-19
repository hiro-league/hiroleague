import { describe, expect, it } from 'vitest';
import type { GraphEdgeDTO, GraphNodeDTO } from '$lib/api/knowledge';
import {
  computeCappedEdgeIds,
  computeMatchedNodeIds,
  computeNodeInstanceFacets,
  edgeIsCurrent,
  epoch,
  normalizeRange,
  passesRange
} from './graph-filter-pure';

function node(id: string, type = 'Person', name = id): GraphNodeDTO {
  return {
    id,
    type,
    name,
    aliases: [],
    chunk_ids: [],
    document_ids: [],
    summary: ''
  };
}

function edge(
  id: string,
  source: string,
  target: string,
  rel = 'RELATES_TO',
  valid_at: string | null = '2024-01-15T00:00:00.000Z'
): GraphEdgeDTO {
  return {
    id,
    source,
    target,
    rel_type: rel,
    fact: '',
    chunk_ids: [],
    document_ids: [],
    valid_at,
    created_at: valid_at,
    invalid_at: null,
    expired_at: null
  };
}

describe('epoch', () => {
  it('parses ISO timestamps', () => {
    expect(epoch('2024-01-15T00:00:00.000Z')).toBe(Date.parse('2024-01-15T00:00:00.000Z'));
  });

  it('returns null for empty input', () => {
    expect(epoch(null)).toBeNull();
    expect(epoch('')).toBeNull();
  });
});

describe('normalizeRange', () => {
  const span = { lo: 1000, hi: 2000 };

  it('returns null when range covers full span', () => {
    expect(normalizeRange({ lo: 1000, hi: 2000 }, span)).toBeNull();
  });

  it('clamps partial ranges', () => {
    expect(normalizeRange({ lo: 1500, hi: 2000 }, span)).toEqual({ lo: 1500, hi: 2000 });
  });
});

describe('edgeIsCurrent', () => {
  it('treats edges without invalid/expired as current', () => {
    expect(edgeIsCurrent(edge('e1', 'a', 'b'))).toBe(true);
  });

  it('treats invalidated edges as not current', () => {
    const e = edge('e1', 'a', 'b');
    e.invalid_at = '2024-02-01T00:00:00.000Z';
    expect(edgeIsCurrent(e)).toBe(false);
  });
});

describe('passesRange', () => {
  const range = { lo: 100, hi: 200 };

  it('passes when range inactive', () => {
    expect(passesRange(50, null, true)).toBe(true);
  });

  it('respects includeUndatedEdges for null values', () => {
    expect(passesRange(null, range, true)).toBe(true);
    expect(passesRange(null, range, false)).toBe(false);
  });
});

describe('computeNodeInstanceFacets', () => {
  it('groups nodes by type with visibility counts', () => {
    const nodes = [node('n1', 'Person'), node('n2', 'Person'), node('n3', 'Place')];
    const links = [edge('e1', 'n1', 'n2')];
    const hidden = new Set(['n2']);
    const facets = computeNodeInstanceFacets(nodes, links, hidden);
    const person = facets.find((f) => f.type === 'Person');
    expect(person?.count).toBe(2);
    expect(person?.visibleCount).toBe(1);
    expect(person?.selectedIds).toEqual(['n1']);
  });
});

describe('computeCappedEdgeIds', () => {
  it('returns null when cap is at maximum (no limit)', () => {
    const links = [edge('e1', 'a', 'b'), edge('e2', 'a', 'c')];
    expect(computeCappedEdgeIds(links, 25, 'newest')).toBeNull();
  });

  it('keeps at most N edges per node', () => {
    const links = [
      edge('e1', 'a', 'b', 'R', '2024-01-01T00:00:00.000Z'),
      edge('e2', 'a', 'c', 'R', '2024-02-01T00:00:00.000Z'),
      edge('e3', 'a', 'd', 'R', '2024-03-01T00:00:00.000Z')
    ];
    const kept = computeCappedEdgeIds(links, 2, 'newest');
    expect(kept?.size).toBe(2);
  });
});

describe('computeMatchedNodeIds', () => {
  it('matches by name substring', () => {
    const nodes = [node('n1', 'Person', 'Alice'), node('n2', 'Person', 'Bob')];
    const matched = computeMatchedNodeIds(nodes, {
      searchQuery: 'ali',
      matchedChunkIds: new Set(),
      episodeChunkIds: new Set()
    });
    expect([...matched]).toEqual(['n1']);
  });
});
