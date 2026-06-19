/**
 * Knowledge Graph tab controller (graph viz MVP).
 *
 * Thin composition root: delegates to sub-factories under `state/graph/`.
 * See docs/knowledge-graph-viz-design.md for load/SSE strategy.
 */

export type { KnowledgeGraphModelDeps } from './graph/create-knowledge-graph-model.svelte';

export type {
  DateRange,
  EdgeValidity,
  GraphNodeInstanceOption,
  GraphNodeTypeGroup,
  GraphSelection,
  GraphTypeFacet,
  LowConnTreatment,
  MaxConnBy
} from './graph/graph-types';

export {
  LOW_CONN_THRESHOLD_DEFAULT,
  LOW_CONN_THRESHOLD_MIN,
  MAX_CONN_PER_NODE_CAP,
  VISIBLE_EDGES_CAP,
  VISIBLE_EDGES_MIN
} from './graph/graph-types';

export {
  createKnowledgeGraphModel,
  type KnowledgeGraphModel
} from './graph/create-knowledge-graph-model.svelte';
