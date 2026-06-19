import { describe, expect, it } from 'vitest';
import {
  computeFocusNodeIds,
  computeNeighborFocus,
  computeRenderSubset,
  isSearchHideMode
} from './graph-render-pure';

describe('computeFocusNodeIds', () => {
  it('returns null when search inactive', () => {
    expect(computeFocusNodeIds(false, new Set(['a']), new Set(), [])).toBeNull();
  });

  it('includes edge endpoints for matched edges', () => {
    const ids = computeFocusNodeIds(
      true,
      new Set(),
      new Set(['e1']),
      [{ id: 'e1', source: 'a', target: 'b', rel_type: 'REL' }]
    );
    expect([...(ids ?? [])].sort()).toEqual(['a', 'b']);
  });
});

describe('computeRenderSubset', () => {
  it('filters nodes in hide mode', () => {
    const nodes = [{ id: 'a' }, { id: 'b' }] as never[];
    const { renderNodes } = computeRenderSubset({
      visibleNodes: nodes,
      displayLinks: [],
      hideMode: true,
      focusNodeIds: new Set(['a']),
      matchedEdgeIds: new Set()
    });
    expect(renderNodes.map((n) => n.id)).toEqual(['a']);
  });
});

describe('computeNeighborFocus', () => {
  it('is inactive while search is active', () => {
    expect(
      computeNeighborFocus({
        searchActive: true,
        selectionFocusMode: 'dim',
        selectedNodeId: 'n1',
        selectedEdgeId: null,
        displayLinks: []
      }).active
    ).toBe(false);
  });

  it('builds ego network for selected node', () => {
    const focus = computeNeighborFocus({
      searchActive: false,
      selectionFocusMode: 'dim',
      selectedNodeId: 'a',
      selectedEdgeId: null,
      displayLinks: [{ id: 'e1', source: 'a', target: 'b', rel_type: 'REL' }]
    });
    expect(focus.active).toBe(true);
    expect([...focus.nodeIds].sort()).toEqual(['a', 'b']);
    expect([...focus.edgeIds]).toEqual(['e1']);
  });
});

describe('isSearchHideMode', () => {
  it('detects hide mode', () => {
    expect(isSearchHideMode({ searchActive: true, searchFocusMode: 'hide' })).toBe(true);
    expect(isSearchHideMode({ searchActive: true, searchFocusMode: 'dim' })).toBe(false);
  });
});
