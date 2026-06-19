import {
  GRAPH_OPTION_DEFAULTS,
  readGraphOptions,
  writeGraphOptions,
  type GraphOptions,
  type SearchFocusMode,
  type SelectionFocusMode
} from '../../graph/knowledge-graph-prefs';

export type GraphOptionsStateDeps = {
  /** Called when the global options reset also clears edge filters. */
  resetEdgeFilters: () => void;
};

/** Reactive graph view options (sliders + focus modes), with localStorage persistence. */
export function createGraphOptionsState(deps: GraphOptionsStateDeps) {
  const saved = readGraphOptions();
  let linkStrength = $state(saved.linkStrength);
  let linkDistance = $state(saved.linkDistance);
  let centerStrength = $state(saved.centerStrength);
  let radialRing = $state(saved.radialRing);
  let curveAmount = $state(saved.curveAmount);
  let chargeStrength = $state(saved.chargeStrength);
  let hubSeparation = $state(saved.hubSeparation);
  let hubSpacing = $state(saved.hubSpacing);
  let collideScale = $state(saved.collideScale);
  let nodeFadeStart = $state(saved.nodeFadeStart);
  let nodeFadeFull = $state(saved.nodeFadeFull);
  let nodeRevealLo = $state(saved.nodeRevealLo);
  let nodeRevealHi = $state(saved.nodeRevealHi);
  let nodeSizeMin = $state(saved.nodeSizeMin);
  let nodeSizeMax = $state(saved.nodeSizeMax);
  let searchFocusMode = $state<SearchFocusMode>(saved.searchFocusMode);
  let selectionFocusMode = $state<SelectionFocusMode>(saved.selectionFocusMode);
  let edgeZoomMin = $state(saved.edgeZoomMin);
  let edgeZoomMax = $state(saved.edgeZoomMax);
  let edgeFontMin = $state(saved.edgeFontMin);
  let edgeFontMax = $state(saved.edgeFontMax);
  let nodeZoomMin = $state(saved.nodeZoomMin);
  let nodeZoomMax = $state(saved.nodeZoomMax);
  let nodeFontMin = $state(saved.nodeFontMin);
  let nodeFontMax = $state(saved.nodeFontMax);
  let edgeLabelMax = $state(saved.edgeLabelMax);

  function snapshot(): GraphOptions {
    return {
      linkStrength,
      linkDistance,
      centerStrength,
      radialRing,
      curveAmount,
      chargeStrength,
      hubSeparation,
      hubSpacing,
      collideScale,
      nodeFadeStart,
      nodeFadeFull,
      nodeRevealLo,
      nodeRevealHi,
      nodeSizeMin,
      nodeSizeMax,
      searchFocusMode,
      selectionFocusMode,
      edgeZoomMin,
      edgeZoomMax,
      edgeFontMin,
      edgeFontMax,
      nodeZoomMin,
      nodeZoomMax,
      nodeFontMin,
      nodeFontMax,
      edgeLabelMax
    };
  }

  function persist(): void {
    writeGraphOptions(snapshot());
  }

  $effect(() => {
    persist();
  });

  function reset(): void {
    const d = GRAPH_OPTION_DEFAULTS;
    linkStrength = d.linkStrength;
    linkDistance = d.linkDistance;
    centerStrength = d.centerStrength;
    radialRing = d.radialRing;
    curveAmount = d.curveAmount;
    chargeStrength = d.chargeStrength;
    hubSeparation = d.hubSeparation;
    hubSpacing = d.hubSpacing;
    collideScale = d.collideScale;
    nodeFadeStart = d.nodeFadeStart;
    nodeFadeFull = d.nodeFadeFull;
    nodeRevealLo = d.nodeRevealLo;
    nodeRevealHi = d.nodeRevealHi;
    nodeSizeMin = d.nodeSizeMin;
    nodeSizeMax = d.nodeSizeMax;
    searchFocusMode = d.searchFocusMode;
    selectionFocusMode = d.selectionFocusMode;
    edgeZoomMin = d.edgeZoomMin;
    edgeZoomMax = d.edgeZoomMax;
    edgeFontMin = d.edgeFontMin;
    edgeFontMax = d.edgeFontMax;
    nodeZoomMin = d.nodeZoomMin;
    nodeZoomMax = d.nodeZoomMax;
    nodeFontMin = d.nodeFontMin;
    nodeFontMax = d.nodeFontMax;
    edgeLabelMax = d.edgeLabelMax;
    deps.resetEdgeFilters();
  }

  return {
    get linkStrength() {
      return linkStrength;
    },
    set linkStrength(v: number) {
      linkStrength = v;
    },
    get linkDistance() {
      return linkDistance;
    },
    set linkDistance(v: number) {
      linkDistance = v;
    },
    get centerStrength() {
      return centerStrength;
    },
    set centerStrength(v: number) {
      centerStrength = v;
    },
    get radialRing() {
      return radialRing;
    },
    set radialRing(v: number) {
      radialRing = v;
    },
    get curveAmount() {
      return curveAmount;
    },
    set curveAmount(v: number) {
      curveAmount = v;
    },
    get chargeStrength() {
      return chargeStrength;
    },
    set chargeStrength(v: number) {
      chargeStrength = v;
    },
    get hubSeparation() {
      return hubSeparation;
    },
    set hubSeparation(v: number) {
      hubSeparation = v;
    },
    get hubSpacing() {
      return hubSpacing;
    },
    set hubSpacing(v: number) {
      hubSpacing = v;
    },
    get collideScale() {
      return collideScale;
    },
    set collideScale(v: number) {
      collideScale = v;
    },
    get nodeFadeStart() {
      return nodeFadeStart;
    },
    set nodeFadeStart(v: number) {
      nodeFadeStart = v;
    },
    get nodeFadeFull() {
      return nodeFadeFull;
    },
    set nodeFadeFull(v: number) {
      nodeFadeFull = v;
    },
    get nodeRevealLo() {
      return nodeRevealLo;
    },
    set nodeRevealLo(v: number) {
      nodeRevealLo = v;
    },
    get nodeRevealHi() {
      return nodeRevealHi;
    },
    set nodeRevealHi(v: number) {
      nodeRevealHi = v;
    },
    get nodeSizeMin() {
      return nodeSizeMin;
    },
    set nodeSizeMin(v: number) {
      nodeSizeMin = v;
    },
    get nodeSizeMax() {
      return nodeSizeMax;
    },
    set nodeSizeMax(v: number) {
      nodeSizeMax = v;
    },
    get searchFocusMode() {
      return searchFocusMode;
    },
    set searchFocusMode(v: SearchFocusMode) {
      searchFocusMode = v;
    },
    get selectionFocusMode() {
      return selectionFocusMode;
    },
    set selectionFocusMode(v: SelectionFocusMode) {
      selectionFocusMode = v;
    },
    get edgeZoomMin() {
      return edgeZoomMin;
    },
    set edgeZoomMin(v: number) {
      edgeZoomMin = v;
    },
    get edgeZoomMax() {
      return edgeZoomMax;
    },
    set edgeZoomMax(v: number) {
      edgeZoomMax = v;
    },
    get edgeFontMin() {
      return edgeFontMin;
    },
    set edgeFontMin(v: number) {
      edgeFontMin = v;
    },
    get edgeFontMax() {
      return edgeFontMax;
    },
    set edgeFontMax(v: number) {
      edgeFontMax = v;
    },
    get nodeZoomMin() {
      return nodeZoomMin;
    },
    set nodeZoomMin(v: number) {
      nodeZoomMin = v;
    },
    get nodeZoomMax() {
      return nodeZoomMax;
    },
    set nodeZoomMax(v: number) {
      nodeZoomMax = v;
    },
    get nodeFontMin() {
      return nodeFontMin;
    },
    set nodeFontMin(v: number) {
      nodeFontMin = v;
    },
    get nodeFontMax() {
      return nodeFontMax;
    },
    set nodeFontMax(v: number) {
      nodeFontMax = v;
    },
    get edgeLabelMax() {
      return edgeLabelMax;
    },
    set edgeLabelMax(v: number) {
      edgeLabelMax = v;
    },
    reset
  };
}

export type GraphOptionsState = ReturnType<typeof createGraphOptionsState>;
