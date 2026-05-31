import { base } from '$app/paths';
import type {
  GraphEdgeEvent,
  GraphIngestProgress,
  GraphNodeEvent,
  KnowledgeJobData
} from '$lib/api/knowledge';
import { PREF_KEYS } from '$lib/preferences/keys';
import { knowledgeJobFromEvent } from './knowledge-jobs';

const KNOWLEDGE_JOB_EVENT_TYPES = [
  'knowledge.job.started',
  'knowledge.job.progress',
  'knowledge.job.completed',
  'knowledge.job.failed'
] as const;

/** Subscribe to knowledge ingest job SSE updates; returns teardown. */
export function connectKnowledgeJobEvents(onJob: (job: KnowledgeJobData) => void): () => void {
  const selectedWorkspace =
    typeof localStorage === 'undefined' ? null : localStorage.getItem(PREF_KEYS.selectedWorkspace);
  const queryParam = selectedWorkspace ? `?workspace=${encodeURIComponent(selectedWorkspace)}` : '';
  const source = new EventSource(`${base}/api/knowledge/events${queryParam}`);

  const handler = (event: MessageEvent) => {
    const job = knowledgeJobFromEvent(event);
    if (job) onJob(job);
  };

  for (const type of KNOWLEDGE_JOB_EVENT_TYPES) {
    source.addEventListener(type, handler);
  }
  return () => source.close();
}

// ---------------------------------------------------------------------------
// L3 (Phase 5e) — eval batch event subscriber. Same SSE stream as above,
// different event types — the controller dispatches on event.type.
// ---------------------------------------------------------------------------

/** Payload shape of ``knowledge.eval.started`` events. */
export type EvalStartedPayload = {
  run_id: string;
  total_questions: number;
  filters: Record<string, unknown>;
};

/** Per-leg result inside a ``knowledge.eval.question_completed`` event. */
export type EvalQuestionLeg = {
  mark: string;            // ✓ / ◐ / ✗ / 🛇
  elapsed_ms: number;
  answer_preview: string;
  run_id: string | null;   // per-leg knowledge_answer ledger run for drill-in
};

/** Payload shape of ``knowledge.eval.question_completed`` events. */
export type EvalQuestionPayload = {
  index: number;
  total: number;
  id: string;
  category: string;
  question: string;
  requires_graph: boolean;
  flat: EvalQuestionLeg;
  graph: EvalQuestionLeg;
  delta: string;
};

/** Payload shape of ``knowledge.eval.completed`` events (aggregate summary). */
export type EvalCompletedPayload = {
  run_id: string;
  total_questions: number;
  flat_passing: number;
  graph_passing: number;
  requires_graph_total: number;
  requires_graph_flat_passing: number;
  requires_graph_graph_passing: number;
  graph_wins: number;
  graph_loses: number;
  ties: number;
  gate: 'proceed' | 'pivot';
  elapsed_ms: number;
};

/** Payload shape of ``knowledge.eval.failed`` events. */
export type EvalFailedPayload = {
  run_id: string;
  error: string;
};

/** Payload shape of ``knowledge.eval.setup_progress`` events. */
export type EvalSetupProgressPayload = {
  phase: 'ingest_synthetic' | 'graph_build';
  file_count?: number;
};

export type EvalEventHandlers = {
  onStarted?: (p: EvalStartedPayload) => void;
  onSetupProgress?: (p: EvalSetupProgressPayload) => void;
  onQuestion?: (p: EvalQuestionPayload) => void;
  onCompleted?: (p: EvalCompletedPayload) => void;
  onFailed?: (p: EvalFailedPayload) => void;
};

const KNOWLEDGE_EVAL_EVENT_TYPES = [
  'knowledge.eval.started',
  'knowledge.eval.setup_progress',
  'knowledge.eval.question_completed',
  'knowledge.eval.completed',
  'knowledge.eval.failed'
] as const;

/** Subscribe to L3 eval batch SSE events; returns teardown. */
export function connectKnowledgeEvalEvents(handlers: EvalEventHandlers): () => void {
  const selectedWorkspace =
    typeof localStorage === 'undefined' ? null : localStorage.getItem(PREF_KEYS.selectedWorkspace);
  const queryParam = selectedWorkspace ? `?workspace=${encodeURIComponent(selectedWorkspace)}` : '';
  const source = new EventSource(`${base}/api/knowledge/events${queryParam}`);

  const parse = <T>(event: MessageEvent): T | null => {
    try {
      return JSON.parse(event.data) as T;
    } catch {
      // Malformed payload — drop it rather than crashing the table render.
      return null;
    }
  };

  const dispatch: Record<string, (e: MessageEvent) => void> = {
    'knowledge.eval.started': (e) => {
      const p = parse<EvalStartedPayload>(e);
      if (p && handlers.onStarted) handlers.onStarted(p);
    },
    'knowledge.eval.setup_progress': (e) => {
      const p = parse<EvalSetupProgressPayload>(e);
      if (p && handlers.onSetupProgress) handlers.onSetupProgress(p);
    },
    'knowledge.eval.question_completed': (e) => {
      const p = parse<EvalQuestionPayload>(e);
      if (p && handlers.onQuestion) handlers.onQuestion(p);
    },
    'knowledge.eval.completed': (e) => {
      const p = parse<EvalCompletedPayload>(e);
      if (p && handlers.onCompleted) handlers.onCompleted(p);
    },
    'knowledge.eval.failed': (e) => {
      const p = parse<EvalFailedPayload>(e);
      if (p && handlers.onFailed) handlers.onFailed(p);
    }
  };

  for (const type of KNOWLEDGE_EVAL_EVENT_TYPES) {
    source.addEventListener(type, dispatch[type]);
  }
  return () => source.close();
}

// ---------------------------------------------------------------------------
// Graph viz (MVP) — live node/edge updates for the admin "Graph" tab. Same
// SSE stream, separate event types — the panel pops new nodes/edges as the
// graph builds. See docs/knowledge-graph-viz-design.md.
// ---------------------------------------------------------------------------

export type KnowledgeGraphEventHandlers = {
  onNode?: (p: GraphNodeEvent) => void;
  onEdge?: (p: GraphEdgeEvent) => void;
  onProgress?: (p: GraphIngestProgress) => void;
  onCompleted?: () => void;
};

const KNOWLEDGE_GRAPH_EVENT_TYPES = [
  'knowledge.graph.node_upserted',
  'knowledge.graph.edge_upserted',
  'knowledge.graph.ingest_progress',
  'knowledge.graph.ingest_completed'
] as const;

/** Subscribe to L3 graph-viz SSE events; returns teardown. */
export function connectKnowledgeGraphEvents(handlers: KnowledgeGraphEventHandlers): () => void {
  const selectedWorkspace =
    typeof localStorage === 'undefined' ? null : localStorage.getItem(PREF_KEYS.selectedWorkspace);
  const queryParam = selectedWorkspace
    ? `?workspace=${encodeURIComponent(selectedWorkspace)}`
    : '';
  const source = new EventSource(`${base}/api/knowledge/events${queryParam}`);

  const parse = <T>(event: MessageEvent): T | null => {
    try {
      return JSON.parse(event.data) as T;
    } catch {
      // Malformed payload — drop it; keep the stream alive.
      return null;
    }
  };

  const dispatch: Record<string, (e: MessageEvent) => void> = {
    'knowledge.graph.node_upserted': (e) => {
      const p = parse<GraphNodeEvent>(e);
      if (p && handlers.onNode) handlers.onNode(p);
    },
    'knowledge.graph.edge_upserted': (e) => {
      const p = parse<GraphEdgeEvent>(e);
      if (p && handlers.onEdge) handlers.onEdge(p);
    },
    'knowledge.graph.ingest_progress': (e) => {
      const p = parse<GraphIngestProgress>(e);
      if (p && handlers.onProgress) handlers.onProgress(p);
    },
    'knowledge.graph.ingest_completed': () => {
      handlers.onCompleted?.();
    }
  };

  for (const type of KNOWLEDGE_GRAPH_EVENT_TYPES) {
    source.addEventListener(type, dispatch[type]);
  }
  return () => source.close();
}
