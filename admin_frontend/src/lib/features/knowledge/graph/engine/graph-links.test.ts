import { describe, expect, it } from 'vitest';
import { collapseParallelLinks, type AggregateLink } from './graph-links';

/** Minimal edge shape the collapse needs (id + endpoints + valid_at for newest/oldest ranking). */
type E = { id: string; source: string; target: string; valid_at: string | null };
const e = (id: string, source: string, target: string, valid_at: string | null = null): E => ({
  id,
  source,
  target,
  valid_at
});
const CAP = 100;
const isAgg = (l: unknown): l is AggregateLink => !!(l as { aggregate?: boolean }).aggregate;

describe('collapseParallelLinks', () => {
  it('returns links untouched when visibleEdges >= cap ("All")', () => {
    const links = [e('1', 'a', 'b'), e('2', 'a', 'b'), e('3', 'a', 'b')];
    expect(collapseParallelLinks(links, CAP, 'newest', CAP)).toBe(links);
  });

  it('shows all edges of a pair that fits the cap — no "1 more" at an exact fit', () => {
    const links = [e('1', 'a', 'b'), e('2', 'a', 'b')]; // Z == V == 2
    const out = collapseParallelLinks(links, 2, 'newest', CAP);
    expect(out).toHaveLength(2);
    expect(out.some(isAgg)).toBe(false);
  });

  it('collapses a pair past the cap into V-1 real edges + 1 aggregate (the worked example)', () => {
    // Z = 10, V = 2 → 1 real edge + 1 "9 other relations" aggregate.
    const links = Array.from({ length: 10 }, (_, i) =>
      e(`r${i}`, 'a', 'b', `2020-01-${String(i + 1).padStart(2, '0')}T00:00:00Z`)
    );
    const out = collapseParallelLinks(links, 2, 'newest', CAP);
    const reals = out.filter((l) => !isAgg(l));
    const aggs = out.filter(isAgg);
    expect(reals).toHaveLength(1);
    expect(aggs).toHaveLength(1);
    expect(aggs[0].collapsedIds).toHaveLength(9);
    expect(aggs[0].whole).toBe(false); // a real edge is shown alongside → "9 other relations"
    // 'newest' keeps the latest valid_at (r9); the aggregate carries the other 9.
    expect(reals[0].id).toBe('r9');
    expect(aggs[0].collapsedIds).not.toContain('r9');
    // Aggregate sits on the same pair and carries no rel_type.
    expect(aggs[0].source).toBe('a');
    expect(aggs[0].target).toBe('b');
    expect(aggs[0].rel_type).toBe('');
  });

  it('at visibleEdges=1 folds the WHOLE multi-edge pair into one aggregate (whole=true, "X relations")', () => {
    const links = [e('1', 'a', 'b'), e('2', 'a', 'b'), e('3', 'a', 'b')];
    const out = collapseParallelLinks(links, 1, 'newest', CAP);
    const reals = out.filter((l) => !isAgg(l));
    const aggs = out.filter(isAgg);
    expect(reals).toHaveLength(0); // no real edge shown — the aggregate IS the pair
    expect(aggs).toHaveLength(1);
    expect(aggs[0].collapsedIds).toHaveLength(3); // X = the full relation count between a and b
    expect(aggs[0].whole).toBe(true);
  });

  it('at visibleEdges=1 a singleton pair stays a normal edge (only multi-edge pairs fold)', () => {
    const links = [e('1', 'a', 'b'), e('2', 'c', 'd'), e('3', 'c', 'd')];
    const out = collapseParallelLinks(links, 1, 'newest', CAP);
    expect(out.some((l) => !isAgg(l) && l.id === '1')).toBe(true); // a-b (1 edge) shown as-is
    const aggs = out.filter(isAgg);
    expect(aggs).toHaveLength(1); // only c-d (2 edges) folds
    expect(aggs[0].whole).toBe(true);
    expect(aggs[0].collapsedIds).toHaveLength(2);
  });

  it("'oldest' keeps the earliest edge instead", () => {
    const links = Array.from({ length: 5 }, (_, i) =>
      e(`r${i}`, 'a', 'b', `2020-01-0${i + 1}T00:00:00Z`)
    );
    const out = collapseParallelLinks(links, 2, 'oldest', CAP);
    const reals = out.filter((l) => !isAgg(l));
    expect(reals.map((l) => l.id)).toEqual(['r0']); // earliest valid_at kept
  });

  it('aggregates each pair independently and leaves singleton pairs alone', () => {
    const links = [
      e('1', 'a', 'b'),
      e('2', 'a', 'b'),
      e('3', 'a', 'b'), // pair a-b has 3 → collapses at V=2
      e('4', 'c', 'd') // lone edge → untouched
    ];
    const out = collapseParallelLinks(links, 2, 'newest', CAP);
    const aggs = out.filter(isAgg);
    expect(aggs).toHaveLength(1);
    expect(aggs[0].collapsedIds).toHaveLength(2);
    expect(out.some((l) => !isAgg(l) && l.id === '4')).toBe(true);
    // Stable, pair-scoped aggregate id (unordered key) so the engine mirror keeps identity.
    expect(aggs[0].id).toBe('__agg:a b');
  });

  it('treats A->B and B->A as the same pair', () => {
    const links = [e('1', 'a', 'b'), e('2', 'b', 'a'), e('3', 'a', 'b')];
    const out = collapseParallelLinks(links, 2, 'newest', CAP);
    expect(out.filter(isAgg)).toHaveLength(1);
  });
});
