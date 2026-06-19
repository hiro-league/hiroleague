import { untrack } from 'svelte';
import type { KnowledgeGraphModel } from '../knowledge-graph.svelte';
import type { GraphCanvasEngine } from '../../graph/engine/graph-canvas-engine';
import type { NeighborFocusState, SearchState } from '../../graph/engine/graph-engine-types';
import {
  computeFocusNodeIds,
  computeNeighborFocus,
  computeRenderSubset,
  isSearchHideMode,
  type DisplayLink
} from './graph-render-pure';

export type GraphEngineBridgeOptions = {
  getGraph: () => KnowledgeGraphModel;
  getEngine: () => GraphCanvasEngine | null;
  getDisplayLinks: () => DisplayLink[];
  getForceOptions: () => {
    linkStrength: number;
    linkDistance: number;
    centerStrength: number;
    radialRing: number;
    chargeStrength: number;
    hubSeparation: number;
    hubSpacing: number;
    collideScale: number;
  };
  getCurveAmount: () => number;
  getNodeSizing: () => { minSize: number; maxSize: number };
  getLabelSizing: () => {
    edgeZoomMin: number;
    edgeZoomMax: number;
    edgeFontMin: number;
    edgeFontMax: number;
    nodeZoomMin: number;
    nodeZoomMax: number;
    nodeFontMin: number;
    nodeFontMax: number;
    edgeLabelMax: number;
  };
  getNodeFade: () => {
    nodeFadeStart: number;
    nodeFadeFull: number;
    nodeRevealLo: number;
    nodeRevealHi: number;
  };
  getSearchFocusMode: () => import('../../graph/knowledge-graph-prefs').SearchFocusMode;
  getSelectionFocusMode: () => import('../../graph/knowledge-graph-prefs').SelectionFocusMode;
};

/** Sync reactive model/option reads into the canvas engine via $effect blocks. */
export function createGraphEngineBridge(opts: GraphEngineBridgeOptions): {
  getRenderNodes: () => import('$lib/api/knowledge').GraphNodeDTO[];
  getRenderLinks: () => DisplayLink[];
  getFocusNodeIds: () => Set<string> | null;
  getNeighborFocus: () => NeighborFocusState;
} {
  const searchActive = $derived(opts.getGraph().searchActive());
  const matchedNodeIds = $derived(opts.getGraph().matchedNodeIds());
  const matchedEdgeIds = $derived(opts.getGraph().matchedEdgeIds());
  const displayLinks = $derived(opts.getDisplayLinks());

  const focusNodeIds = $derived.by(() =>
    computeFocusNodeIds(searchActive, matchedNodeIds, matchedEdgeIds, displayLinks)
  );

  const hideMode = $derived(
    isSearchHideMode({ searchActive, searchFocusMode: opts.getSearchFocusMode() })
  );

  // One computation per change; both render arrays derive from the same subset so the
  // subset isn't recomputed twice on every reactive tick.
  const renderSubset = $derived.by(() =>
    computeRenderSubset({
      visibleNodes: opts.getGraph().visibleNodes(),
      displayLinks,
      hideMode,
      focusNodeIds,
      matchedEdgeIds
    })
  );
  const renderNodes = $derived(renderSubset.renderNodes);
  const renderLinks = $derived(renderSubset.renderLinks);

  const selectedNodeId = $derived(
    opts.getGraph().selected()?.kind === 'node'
      ? (opts.getGraph().selected() as { id: string }).id
      : null
  );
  const selectedEdgeId = $derived(
    opts.getGraph().selected()?.kind === 'edge'
      ? (opts.getGraph().selected() as { id: string }).id
      : null
  );

  const neighborFocus = $derived.by(() =>
    computeNeighborFocus({
      searchActive,
      selectionFocusMode: opts.getSelectionFocusMode(),
      selectedNodeId,
      selectedEdgeId,
      displayLinks
    })
  );

  let lastLoadVersion = -1;
  let lastHiddenNodes: Set<string> | null = null;
  let lastHiddenEdges: Set<string> | null = null;
  let lastFilterToken: string | null = null;
  let lastRenderNodes: unknown = null;
  let lastRenderLinks: unknown = null;
  let lastRecent: Record<string, number> | null = null;
  let lastForcesKey = '';
  let lastCurve = NaN;
  let lastNodeSizingKey = '';
  let lastDenoiseKey = '';
  let lastLabelKey = '';
  let lastFadeKey = '';
  let lastSearchKey = '';
  let lastNeighborKey = '';
  let lastSelectionKey = '';
  let lastReframeHiddenNodes: Set<string> | null = null;
  let lastReframeHiddenEdges: Set<string> | null = null;
  let lastReframeFilterToken: string | null = null;

  $effect(() => {
    const nodes = renderNodes;
    const links = renderLinks;
    const loadVersion = opts.getGraph().loadVersion();
    const hiddenNodeIds = opts.getGraph().hiddenNodeIds();
    const hiddenEdgeTypes = opts.getGraph().hiddenEdgeTypes();
    const filterToken = opts.getGraph().filterToken();
    if (
      loadVersion === lastLoadVersion &&
      hiddenNodeIds === lastHiddenNodes &&
      hiddenEdgeTypes === lastHiddenEdges &&
      filterToken === lastFilterToken &&
      nodes === lastRenderNodes &&
      links === lastRenderLinks
    ) {
      return;
    }
    // Check the engine BEFORE recording the synced snapshot: if it isn't mounted yet we must
    // not poison the dedup cache, or the first post-mount data push could be skipped.
    const engine = opts.getEngine();
    if (!engine) return;
    lastLoadVersion = loadVersion;
    lastHiddenNodes = hiddenNodeIds;
    lastHiddenEdges = hiddenEdgeTypes;
    lastFilterToken = filterToken;
    lastRenderNodes = nodes;
    lastRenderLinks = links;
    untrack(() =>
      engine.setData(nodes, links, { loadVersion, hiddenNodeIds, hiddenEdgeTypes, filterToken })
    );
  });

  $effect(() => {
    const recent = opts.getGraph().recent();
    if (recent === lastRecent) return;
    lastRecent = recent;
    opts.getEngine()?.setRecent(recent);
  });

  $effect(() => {
    const hiddenNodeIds = opts.getGraph().hiddenNodeIds();
    const hiddenEdgeTypes = opts.getGraph().hiddenEdgeTypes();
    const filterToken = opts.getGraph().filterToken();
    if (
      hiddenNodeIds === lastReframeHiddenNodes &&
      hiddenEdgeTypes === lastReframeHiddenEdges &&
      filterToken === lastReframeFilterToken
    ) {
      return;
    }
    lastReframeHiddenNodes = hiddenNodeIds;
    lastReframeHiddenEdges = hiddenEdgeTypes;
    lastReframeFilterToken = filterToken;
    opts.getEngine()?.markIntentionalReframe();
  });

  $effect(() => {
    const f = opts.getForceOptions();
    const key = JSON.stringify(f);
    if (key === lastForcesKey) return;
    lastForcesKey = key;
    opts.getEngine()?.setForces(f);
  });

  $effect(() => {
    const curve = opts.getCurveAmount();
    if (curve === lastCurve) return;
    lastCurve = curve;
    opts.getEngine()?.setCurveAmount(curve);
  });

  $effect(() => {
    const sizing = opts.getNodeSizing();
    const key = `${sizing.minSize}|${sizing.maxSize}`;
    if (key === lastNodeSizingKey) return;
    lastNodeSizingKey = key;
    opts.getEngine()?.setNodeSizing(sizing);
  });

  $effect(() => {
    const ids = opts.getGraph().lowConnDimIds();
    const key = [...ids].sort().join(',');
    if (key === lastDenoiseKey) return;
    lastDenoiseKey = key;
    opts.getEngine()?.setDenoiseDim(ids);
  });

  $effect(() => {
    const l = opts.getLabelSizing();
    const key = JSON.stringify(l);
    if (key === lastLabelKey) return;
    lastLabelKey = key;
    opts.getEngine()?.setLabelSizing(l);
  });

  $effect(() => {
    const fade = opts.getNodeFade();
    const key = JSON.stringify(fade);
    if (key === lastFadeKey) return;
    lastFadeKey = key;
    opts.getEngine()?.setNodeFade(fade);
  });

  $effect(() => {
    const state: SearchState = {
      searchActive,
      matchedNodeIds,
      matchedEdgeIds,
      focusNodeIds,
      searchFocusMode: opts.getSearchFocusMode()
    };
    const key = JSON.stringify({
      searchActive,
      focus: focusNodeIds ? [...focusNodeIds].sort().join(',') : '',
      nodes: [...matchedNodeIds].sort().join(','),
      edges: [...matchedEdgeIds].sort().join(','),
      mode: state.searchFocusMode
    });
    if (key === lastSearchKey) return;
    lastSearchKey = key;
    opts.getEngine()?.setSearch(state);
  });

  $effect(() => {
    const focus = neighborFocus;
    const key = JSON.stringify({
      active: focus.active,
      mode: focus.mode,
      selectedId: focus.selectedId,
      nodes: [...focus.nodeIds].sort().join(','),
      edges: [...focus.edgeIds].sort().join(',')
    });
    if (key === lastNeighborKey) return;
    lastNeighborKey = key;
    opts.getEngine()?.setNeighborFocus(focus);
  });

  $effect(() => {
    const sel = opts.getGraph().selected();
    const key = sel ? `${sel.kind}:${sel.id}` : '';
    if (key === lastSelectionKey) return;
    lastSelectionKey = key;
    opts.getEngine()?.setSelection(sel);
  });

  return {
    getRenderNodes: () => renderNodes,
    getRenderLinks: () => renderLinks,
    getFocusNodeIds: () => focusNodeIds,
    getNeighborFocus: () => neighborFocus
  };
}
