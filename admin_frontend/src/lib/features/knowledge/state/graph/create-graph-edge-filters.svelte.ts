import {
  EDGE_FILTER_DEFAULTS,
  LOW_CONN_THRESHOLD_MIN,
  MAX_CONN_PER_NODE_CAP,
  VISIBLE_EDGES_CAP,
  VISIBLE_EDGES_MIN,
  type DateRange,
  type EdgeValidity,
  type LowConnTreatment,
  type MaxConnBy
} from './graph-types';
import { normalizeRange } from './graph-filter-pure';
import { persistEdgeFilterModes, readEdgeFilterModes } from './graph-persistence';

export function createGraphEdgeFilters(deps: {
  getValidAtSpan: () => { lo: number; hi: number } | null;
  getCreatedAtSpan: () => { lo: number; hi: number } | null;
}) {
  const persisted = readEdgeFilterModes();
  let edgeValidity = $state<EdgeValidity>(persisted.edgeValidity);
  let includeUndatedEdges = $state(persisted.includeUndatedEdges);
  let maxConnPerNode = $state(persisted.maxConnPerNode);
  let maxConnBy = $state<MaxConnBy>(persisted.maxConnBy);
  let visibleEdgesPerPair = $state(persisted.visibleEdgesPerPair);
  let lowConnTreatment = $state<LowConnTreatment>(persisted.lowConnTreatment);
  let lowConnThreshold = $state(persisted.lowConnThreshold);
  let validRange = $state<DateRange>(null);
  let creationRange = $state<DateRange>(null);

  function snapshotModes() {
    return {
      edgeValidity,
      includeUndatedEdges,
      maxConnPerNode,
      maxConnBy,
      visibleEdgesPerPair,
      lowConnTreatment,
      lowConnThreshold
    };
  }

  function persistModes(): void {
    persistEdgeFilterModes(snapshotModes());
  }

  function setEdgeValidity(v: EdgeValidity): void {
    edgeValidity = v;
    persistModes();
  }

  function setIncludeUndatedEdges(on: boolean): void {
    includeUndatedEdges = on;
    persistModes();
  }

  function setMaxConnPerNode(n: number): void {
    maxConnPerNode = Math.min(MAX_CONN_PER_NODE_CAP, Math.max(1, Math.round(n)));
    persistModes();
  }

  function setMaxConnBy(by: MaxConnBy): void {
    maxConnBy = by;
    persistModes();
  }

  function setVisibleEdgesPerPair(n: number): void {
    visibleEdgesPerPair = Math.min(VISIBLE_EDGES_CAP, Math.max(VISIBLE_EDGES_MIN, Math.round(n)));
    persistModes();
  }

  function setLowConnTreatment(t: LowConnTreatment): void {
    lowConnTreatment = t;
    persistModes();
  }

  function setLowConnThreshold(n: number): void {
    lowConnThreshold = Math.max(LOW_CONN_THRESHOLD_MIN, Math.round(n));
    persistModes();
  }

  // Guard against the controlled bits-ui Slider feedback loop: the slider snaps its value to
  // the `step` grid and re-emits onValueChange when we feed a normalized value back in, while
  // normalizeRange snaps to the raw data-span endpoints. The two snappings disagree, so without
  // this equality check the write→derive→re-emit cycle never settles (effect_update_depth_exceeded).
  function rangesEqual(a: DateRange, b: DateRange): boolean {
    if (a === b) return true;
    if (!a || !b) return false;
    return a.lo === b.lo && a.hi === b.hi;
  }

  function setValidRange(range: DateRange): void {
    const next = normalizeRange(range, deps.getValidAtSpan());
    if (rangesEqual(next, validRange)) return;
    validRange = next;
  }

  function setCreationRange(range: DateRange): void {
    const next = normalizeRange(range, deps.getCreatedAtSpan());
    if (rangesEqual(next, creationRange)) return;
    creationRange = next;
  }

  function resetEdgeFilters(): void {
    edgeValidity = EDGE_FILTER_DEFAULTS.edgeValidity;
    includeUndatedEdges = EDGE_FILTER_DEFAULTS.includeUndatedEdges;
    maxConnPerNode = EDGE_FILTER_DEFAULTS.maxConnPerNode;
    maxConnBy = EDGE_FILTER_DEFAULTS.maxConnBy;
    visibleEdgesPerPair = EDGE_FILTER_DEFAULTS.visibleEdgesPerPair;
    lowConnTreatment = EDGE_FILTER_DEFAULTS.lowConnTreatment;
    lowConnThreshold = EDGE_FILTER_DEFAULTS.lowConnThreshold;
    validRange = null;
    creationRange = null;
    persistModes();
  }

  function resetDateRangesOnLoad(): void {
    validRange = null;
    creationRange = null;
  }

  return {
    get edgeValidity() {
      return edgeValidity;
    },
    get includeUndatedEdges() {
      return includeUndatedEdges;
    },
    get maxConnPerNode() {
      return maxConnPerNode;
    },
    get maxConnBy() {
      return maxConnBy;
    },
    get visibleEdgesPerPair() {
      return visibleEdgesPerPair;
    },
    get lowConnTreatment() {
      return lowConnTreatment;
    },
    get lowConnThreshold() {
      return lowConnThreshold;
    },
    get validRange() {
      return validRange;
    },
    get creationRange() {
      return creationRange;
    },
    setEdgeValidity,
    setIncludeUndatedEdges,
    setMaxConnPerNode,
    setMaxConnBy,
    setVisibleEdgesPerPair,
    setLowConnTreatment,
    setLowConnThreshold,
    setValidRange,
    setCreationRange,
    resetEdgeFilters,
    resetDateRangesOnLoad
  };
}

export type GraphEdgeFilters = ReturnType<typeof createGraphEdgeFilters>;
